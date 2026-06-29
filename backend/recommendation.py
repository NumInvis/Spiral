import re
from typing import List, Dict, Optional, Tuple
from sqlalchemy import and_
from sqlalchemy.orm import Session, selectinload, with_loader_criteria

from config import get_province_rule, default_rule
from config.province_rules import CURRENT_YEAR, LATEST_HISTORICAL_YEAR
from models import Profile, School, Major, MajorScore, AdmissionPlan, RankTable
from schemas import RecommendationItem

try:
    from services.major_matcher import build_major_intent, score_major_relevance
except Exception:
    build_major_intent = None
    score_major_relevance = None

# LLM 决策层导入（必须配置，禁止回退）
try:
    from services.llm_service import chat_completion
    LLM_AVAILABLE = True
except Exception:
    chat_completion = None
    LLM_AVAILABLE = False


# ---------------------------------------------------------------------------
# 静态数据内存缓存
# ---------------------------------------------------------------------------
_schools_cache: Dict[Tuple[str, str], List[School]] = {}


def _load_schools_cached(db: Session, province: str, subject_type: str) -> List[School]:
    """加载学校与专业元数据（分数线不再通过此缓存读取）。"""
    global _schools_cache
    key = (province, subject_type)
    if key not in _schools_cache:
        schools = (
            db.query(School)
            .options(
                selectinload(School.majors).selectinload(Major.scores),
                with_loader_criteria(
                    MajorScore,
                    and_(MajorScore.province == province, MajorScore.subject_type == subject_type),
                ),
                selectinload(School.majors).selectinload(Major.plans),
                with_loader_criteria(
                    AdmissionPlan,
                    and_(AdmissionPlan.province == province, AdmissionPlan.subject_type == subject_type),
                ),
            )
            .all()
        )
        db.expunge_all()
        _schools_cache[key] = schools
    return _schools_cache[key]


def clear_schools_cache() -> None:
    global _schools_cache
    _schools_cache = {}


# ---------------------------------------------------------------------------
# 等位分换算：仅在有完整一分一段表时使用，否则报错而非降级
# ---------------------------------------------------------------------------
RankCache = Dict[int, List[Tuple[int, int]]]  # year -> [(score, accumulate), ...] sorted by score desc


def _build_rank_cache(db: Session, province: str, subject_type: str) -> RankCache:
    cache: RankCache = {}
    rows = (
        db.query(RankTable)
        .filter(
            RankTable.province == province,
            RankTable.subject_type == subject_type,
            RankTable.accumulate.isnot(None),
        )
        .order_by(RankTable.year, RankTable.score.desc())
        .all()
    )
    for r in rows:
        cache.setdefault(r.year, []).append((r.score, r.accumulate))
    return cache


def _score_for_rank_cached(cache: RankCache, year: int, rank: int) -> Optional[int]:
    rows = cache.get(year)
    if not rows:
        raise ValueError(f"缺少 {year} 年一分一段表，无法进行等位分换算")
    for i, (score, acc) in enumerate(rows):
        if acc <= rank:
            if i == 0:
                return score
            prev_score, prev_acc = rows[i - 1]
            if prev_acc != acc:
                ratio = (rank - acc) / (prev_acc - acc)
                return int(score + ratio * (prev_score - score))
            return score
    return rows[-1][0]


def _rank_for_score_cached(cache: RankCache, year: int, score: int) -> Optional[int]:
    rows = cache.get(year)
    if not rows:
        raise ValueError(f"缺少 {year} 年一分一段表，无法进行等位分换算")
    for i, (sc, acc) in enumerate(rows):
        if sc == score:
            return acc
        if sc < score:
            if i == 0:
                return acc
            upper_score, upper_acc = rows[i - 1]
            lower_score, lower_acc = sc, acc
            if upper_score == lower_score:
                return upper_acc
            ratio = (score - lower_score) / (upper_score - lower_score)
            return int(lower_acc + ratio * (upper_acc - lower_acc))
    return rows[-1][1]


def rank_to_equivalent(
    candidate_rank: int,
    from_year: int,
    to_year: int,
    province: str,
    subject_type: str,
    db: Optional[Session] = None,
    candidate_score: Optional[int] = None,
    rank_cache: Optional[RankCache] = None,
) -> int:
    """把 from_year 的考生位次换算为 to_year 的等效位次；数据缺失时直接报错。"""
    if from_year == to_year:
        return candidate_rank

    if rank_cache is None and db is not None:
        rank_cache = _build_rank_cache(db, province, subject_type)
    if rank_cache is None:
        raise ValueError("缺少一分一段表，无法进行等位分换算")

    equivalent_score = _score_for_rank_cached(rank_cache, from_year, candidate_rank)

    if equivalent_score is None and candidate_score is not None:
        equivalent_score = candidate_score

    if equivalent_score is not None:
        to_rank = _rank_for_score_cached(rank_cache, to_year, equivalent_score)
        if to_rank is not None:
            return to_rank

    raise ValueError(f"无法将 {from_year} 年位次 {candidate_rank} 换算为 {to_year} 年等效位次")


# ---------------------------------------------------------------------------
# 录取概率：仅基于考生位次与官方投档位次，不使用计划数等不可靠数据
# ---------------------------------------------------------------------------
def estimate_probability(candidate_rank: int, ref_rank: int, plan_count: int = 0, trend: float = 0.0) -> float:
    """基于位次差距估算录取概率；计划数与趋势参数保留签名但不再参与计算。"""
    if ref_rank <= 0:
        return 0.5
    rank_ratio = candidate_rank / ref_rank
    # ratio < 1 表示考生位次更靠前，概率更高
    prob = 1.0 / (1.0 + max(0, rank_ratio - 0.85) * 4.0)
    return max(0.02, min(0.99, prob))


# ---------------------------------------------------------------------------
# 专业语义匹配（LLM 扩展 + 本地打分）
# ---------------------------------------------------------------------------
_intent_cache: Dict[str, Dict] = {}


def major_relevance_score(major_name: str, preferred_majors: Optional[str]) -> float:
    """评估专业名称与考生意向的相关度，返回 0-1 分数。"""
    if not preferred_majors:
        return 0.5
    if build_major_intent is None or score_major_relevance is None:
        return 0.5
    if preferred_majors not in _intent_cache:
        _intent_cache[preferred_majors] = build_major_intent(preferred_majors)
    intent = _intent_cache[preferred_majors]
    score, _ = score_major_relevance(major_name, None, intent)
    return score


# ---------------------------------------------------------------------------
# 特殊类型招生过滤
# ---------------------------------------------------------------------------
# 特殊类型招生分类体系
# 每个类型包含：显示名称、关键词列表、默认是否可见
_SPECIAL_TYPE_CATEGORIES = {
    "国家专项计划": {
        "keywords": ["国家专项", "国家专项计划"],
        "default_visible": False,
    },
    "地方专项计划": {
        "keywords": ["地方专项", "地方专项计划"],
        "default_visible": False,
    },
    "高校专项计划": {
        "keywords": ["高校专项"],
        "default_visible": False,
    },
    "少数民族预科班": {
        "keywords": ["预科", "少数民族预科班"],
        "default_visible": False,
    },
    "民族班": {
        "keywords": ["民族班"],
        "default_visible": False,
    },
    "定向招生": {
        "keywords": ["定向"],
        "default_visible": False,
    },
    "中外合作办学": {
        "keywords": ["中外合作", "中外合作办学"],
        "default_visible": False,
    },
    "护理类": {
        "keywords": ["护理类", "护理学"],
        "default_visible": False,
    },
    "高收费/单列": {
        "keywords": ["高收费"],
        "default_visible": False,
    },
    "公费师范生": {
        "keywords": ["公费师范"],
        "default_visible": False,
    },
    "边防子女预科班": {
        "keywords": ["边防军人子女", "边防子女预科班"],
        "default_visible": False,
    },
    "国际班/海外分校": {
        "keywords": ["国际班", "马来西亚分校"],
        "default_visible": False,
    },
    "援藏/援疆": {
        "keywords": ["援藏", "南疆"],
        "default_visible": False,
    },
}

# 兼容旧代码的扁平关键词列表
_SPECIAL_TYPE_KEYWORDS = [
    kw for cat in _SPECIAL_TYPE_CATEGORIES.values() for kw in cat["keywords"]
]


def classify_special_type(major_name: str, notes: Optional[str]) -> Optional[str]:
    """
    将专业归类为特定特殊类型。
    返回类型名称，如 "国家专项计划"；若不是特殊类型则返回 None。
    """
    text = f"{major_name or ''} {notes or ''}"
    for type_name, config in _SPECIAL_TYPE_CATEGORIES.items():
        if any(kw in text for kw in config["keywords"]):
            return type_name
    return None


def is_special_type(major_name: str, notes: Optional[str]) -> bool:
    text = f"{major_name or ''} {notes or ''}"
    return any(kw in text for kw in _SPECIAL_TYPE_KEYWORDS)


# ---------------------------------------------------------------------------
# 选科匹配增强
# ---------------------------------------------------------------------------
def _subject_requirement_ok(subject_type: str, require: str, profile_text: Optional[str] = None) -> bool:
    """基于考生科类与专业组选科要求做硬性过滤。"""
    req = (require or "不限").strip()
    if req == "不限":
        return True

    if subject_type == "历史":
        return "物" not in req

    # 物理类
    if "化" in req and profile_text:
        if re.search(r"没选化学|不含化学|化学.{0,3}没选|没.{0,2}化学", profile_text):
            return False

    return True


# ---------------------------------------------------------------------------
# 主推荐流程：以最新官方院校专业组投档线为核心，不做专业线热度估算
# ---------------------------------------------------------------------------
def build_recommendation(profile: Profile, db: Session) -> Dict:
    province = profile.province
    subject_type = profile.subject_type
    if not province or not subject_type:
        raise ValueError("缺少省份或科类，无法生成推荐")

    rules = get_province_rule(province) or default_rule()
    max_groups = rules.get("max_groups", 45)
    max_majors = rules.get("max_majors_per_group", 6)

    # 是否允许特殊类型
    allow_special = getattr(profile, "allow_special_types", False)

    # 只查询目标年份（2025）数据，禁止自动回退到旧年份
    # 数据缺失时必须明确报错，由系统触发 web 获取补充，不可静默 fallback
    target_year = LATEST_HISTORICAL_YEAR
    latest_scores = (
        db.query(MajorScore)
        .join(Major)
        .join(School)
        .filter(
            MajorScore.province == province,
            MajorScore.subject_type == subject_type,
            MajorScore.year == target_year,
            MajorScore.group_lowest_rank.isnot(None),
        )
        .options(selectinload(MajorScore.major).selectinload(Major.school))
        .all()
    )

    if not latest_scores:
        raise RuntimeError(
            f"{target_year} 年 {province} {subject_type} 类官方投档线数据缺失，"
            f"无法生成推荐。请确认数据已导入，或配置 web 数据获取。"
        )

    # 按最新年份的组代码聚合专业，分为普通类和特殊类
    group_map: Dict[Tuple[int, str], Dict] = {}          # 普通类
    special_group_map: Dict[Tuple[int, str], Dict] = {}  # 特殊类
    seen_majors: Dict[Tuple[int, str, str], bool] = {}

    for ms in latest_scores:
        major = ms.major
        school = major.school
        gc = ms.group_code or major.group_code or "01"
        key = (school.id, gc)

        # 同组同名/同代码专业去重
        dup_key = (school.id, gc, major.code or major.name)
        if seen_majors.get(dup_key):
            continue
        seen_majors[dup_key] = True

        # 分类：普通类型 vs 特殊类型
        # 同时考虑专业备注（description）和组级别备注（data_source中的2025年备注）
        ms_note = (ms.data_source or "").split(" | ")[-1] if ms.data_source and " | " in ms.data_source else ""
        combined_note = f"{major.description or ''} {ms_note}".strip()
        special_type = classify_special_type(major.name, combined_note)
        is_special = special_type is not None

        if is_special and not allow_special:
            # 用户未允许特殊类型，跳过
            continue

        # 选科过滤（普通类和特殊类都过滤）
        req = major.subject_require or "不限"
        if not _subject_requirement_ok(subject_type, req, profile.preferred_major):
            continue

        # 构建通用专业条目
        relevance = major_relevance_score(major.name, profile.preferred_major)
        prob = estimate_probability(profile.rank, ms.group_lowest_rank)
        major_item = {
            "major": major,
            "probability": prob,
            "ref_rank": ms.group_lowest_rank,
            "ref_score": ms.group_lowest_score,
            "data_confidence": ms.data_confidence,
            "source": ms.data_source or "",
            "relevance": relevance,
            "year_breakdown": [{"year": ms.year, "rank": ms.group_lowest_rank, "score": ms.group_lowest_score, "confidence": ms.data_confidence}],
            "special_type": special_type,  # 新增：类型标记
        }

        if is_special:
            target_map = special_group_map
        else:
            target_map = group_map

        group = target_map.setdefault(key, {
            "school": school,
            "group_code": f"{school.code}{gc.zfill(2)}",
            "subject_type": subject_type,
            "group_lowest_rank": ms.group_lowest_rank,
            "group_lowest_score": ms.group_lowest_score,
            "majors": [],
            "special_type": special_type,  # 组级别标记（取第一个专业的类型）
        })
        group["majors"].append(major_item)

    def _finalize_groups(raw_map: Dict) -> List[Dict]:
        """将聚合的组数据转换为可排序的组列表"""
        groups = []
        for g in raw_map.values():
            if not g["majors"]:
                continue
            g["majors"].sort(key=lambda x: x["relevance"], reverse=True)
            top = g["majors"][:max_majors]
            group_prob = min(i["probability"] for i in top)
            groups.append({
                "school": g["school"],
                "group_code": g["group_code"],
                "subject_type": g["subject_type"],
                "group_lowest_rank": g["group_lowest_rank"],
                "group_lowest_score": g["group_lowest_score"],
                "majors": top,
                "group_prob": group_prob,
                "confidence": "C",
                "avg_relevance": sum(i["relevance"] for i in top) / len(top),
                "special_type": g.get("special_type"),
            })
        return groups

    # 普通类分档
    normal_groups = _finalize_groups(group_map)
    special_groups = _finalize_groups(special_group_map)

    def _school_level_weight(level: Optional[str]) -> float:
        """学校层次权重：985>211>双一流>普通，用于同档次内排序。"""
        if not level:
            return 0.0
        if "985" in level:
            return 2.0
        if "211" in level:
            return 1.0
        if "双一流" in level:
            return 0.5
        return 0.0

    def _sort_key(g: Dict) -> float:
        """综合排序：概率×10 + 专业相关度×5 + 学校层次权重。"""
        return g["group_prob"] * 10 + g["avg_relevance"] * 5 + _school_level_weight(g["school"].level)

    def _partition_and_select(source: List[Dict], target_冲: int, target_稳: int, target_保: int) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        risk_pref = getattr(profile, "risk_preference", "balanced")
        if risk_pref == "aggressive":
            冲_min, 冲_max = 0.05, 0.30
            稳_min, 稳_max = 0.30, 0.60
            保_min = 0.60
        elif risk_pref == "conservative":
            冲_min, 冲_max = 0.20, 0.45
            稳_min, 稳_max = 0.55, 0.85
            保_min = 0.85
        else:
            冲_min, 冲_max = 0.15, 0.45
            稳_min, 稳_max = 0.45, 0.75
            保_min = 0.75

        # 保档上限：不超过当前排名×130%，防止过度保守导致志愿浪费
        max_bao_rank = profile.rank * 1.3

        冲 = [g for g in source if 冲_min <= g["group_prob"] < 冲_max]
        稳 = [g for g in source if 稳_min <= g["group_prob"] < 稳_max]
        保 = [g for g in source if g["group_prob"] >= 保_min and g["group_lowest_rank"] <= max_bao_rank]

        冲.sort(key=_sort_key, reverse=True)
        稳.sort(key=_sort_key, reverse=True)
        保.sort(key=_sort_key, reverse=True)

        def _select_diverse(src: List[Dict], target: int, max_per_school: int = 2) -> List[Dict]:
            selected = []
            counts: Dict[int, int] = {}
            for g in src:
                sid = g["school"].id
                if counts.get(sid, 0) >= max_per_school:
                    continue
                selected.append(g)
                counts[sid] = counts.get(sid, 0) + 1
                if len(selected) >= target:
                    break
            return selected

        selected_冲 = _select_diverse(冲, target_冲)
        selected_稳 = _select_diverse(稳, target_稳)
        selected_保 = _select_diverse(保, target_保)
        return selected_冲, selected_稳, selected_保

    selected_冲, selected_稳, selected_保 = _partition_and_select(normal_groups, 10, 25, 10)
    ordered = selected_冲 + selected_稳 + selected_保

    # 特殊类也按冲稳保分档，但数量更少
    special_冲, special_稳, special_保 = _partition_and_select(special_groups, 3, 8, 3)
    special_ordered = special_冲 + special_稳 + special_保

    # ---------------------------------------------------------------------------
    # LLM 决策层：对候选池进行智能排序和推荐理由生成
    # 禁止回退：LLM 未配置时直接报错，不可静默降级到规则排序
    # ---------------------------------------------------------------------------
    def _llm_decision_layer(
        candidates: List[Dict],
        profile: Profile,
    ) -> Tuple[List[Dict], str]:
        """
        调用 LLM 对候选池进行最终排序和推荐理由生成。
        禁止 fallback：LLM 不可用时必须显式报错，不可回退到规则排序。
        """
        if not LLM_AVAILABLE or chat_completion is None:
            raise RuntimeError(
                "LLM 决策层未激活：未配置 WINCODE_API_KEY 或 OPENAI_API_KEY。"
                "请在 .env 文件中配置 API key 后重试。"
            )

        # 限制候选池大小，避免 LLM 处理超时
        MAX_LLM_CANDIDATES = 5
        llm_candidates = candidates[:MAX_LLM_CANDIDATES]

        # 构建精简候选池描述
        candidate_lines = []
        for idx, g in enumerate(llm_candidates, start=1):
            top_majors = [m["major"].name for m in g["majors"][:2]]
            candidate_lines.append(
                f"{idx}. {g['school'].name} {g['group_code']} | "
                f"位次{g['group_lowest_rank']} | 概率{int(g['group_prob']*100)}% | "
                f"专业：{', '.join(top_majors)}"
            )

        system_prompt = (
            "你是高考志愿填报专家。请根据考生画像和候选池，对候选院校专业组进行排序并给出推荐理由。"
            "输出严格的 JSON 数组，每个元素包含：group_code(专业组代码), reason(1句推荐理由), level(冲/稳/保)。"
            "排序顺序即为推荐顺序。不要输出任何 JSON 之外的文本。"
        )

        user_prompt = (
            f"考生：{profile.province} {profile.subject_type} 位次{profile.rank} "
            f"意向：{profile.preferred_major or '无'}\n"
            f"候选池：\n" + "\n".join(candidate_lines)
        )

        raw = chat_completion(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_prompt}],
            temperature=0.3,
            max_tokens=4096,
            timeout=300.0,
        )

        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        import json
        llm_result = json.loads(raw)

        # 按 LLM 返回的顺序重新排序候选池
        code_to_reason = {}
        for item in llm_result:
            code_to_reason[item["group_code"]] = item

        reordered = []
        for g in candidates:
            if g["group_code"] in code_to_reason:
                g["llm_reason"] = code_to_reason[g["group_code"]].get("reason", "")
                g["llm_risk_notes"] = code_to_reason[g["group_code"]].get("risk_notes", [])
                g["llm_level"] = code_to_reason[g["group_code"]].get("level", "")
                reordered.append(g)
            else:
                # LLM 未覆盖的组：放在末尾，不标注 llm_reason（后续报错）
                reordered.append(g)

        return reordered, "LLM 已完成候选池排序和推荐理由生成"

    # 对普通类候选池调用 LLM 决策层
    ordered, llm_msg = _llm_decision_layer(ordered, profile)

    def _build_recommendation_items(source: List[Dict]) -> List[RecommendationItem]:
        items = []
        for idx, g in enumerate(source, start=1):
            level = "冲" if g in (selected_冲 if source is ordered else special_冲) else (
                "稳" if g in (selected_稳 if source is ordered else special_稳) else "保"
            )
            school = g["school"]
            majors_out = []
            group_year_breakdown = []

            for item in g["majors"]:
                m = item["major"]
                if not group_year_breakdown and item.get("year_breakdown"):
                    group_year_breakdown = item["year_breakdown"]
                majors_out.append({
                    "major_id": m.id,
                    "name": m.name,
                    "category": m.category,
                    "discipline_eval": m.discipline_eval,
                    "probability": round(item["probability"], 2),
                    "ref_rank": item["ref_rank"],
                    "ref_score": item["ref_score"],
                    "data_confidence": item["data_confidence"],
                    "source": item.get("source", ""),
                    "relevance": round(item["relevance"], 2),
                    "special_type": item.get("special_type"),
                })

            gc = g["group_code"]
            school = g["school"]
            gc_group = gc[-2:] if len(gc) >= 2 else gc

            # 提取组内最相关的专业名（构建"这个专业组是什么项目"）
            top_major_names = [m["name"] for m in majors_out if m.get("relevance", 0) >= 0.5][:3]
            group_major_desc = "、".join(top_major_names) if top_major_names else "多方向专业组"

            # LLM 决策层：优先使用 LLM 生成的推荐理由
            if g.get("llm_reason"):
                reason = g["llm_reason"]
                risk_notes = g.get("llm_risk_notes", [])
            else:
                # LLM 未覆盖的组（如候选池超出 LLM 处理范围），使用规则生成但不标注来源
                reason_parts = [
                    f"{school.name}第{gc_group}专业组（{gc}），含{group_major_desc}等方向",
                    f"{LATEST_HISTORICAL_YEAR}年官方投档位次 {g['majors'][0]['ref_rank']}",
                    f"考生位次 {profile.rank}",
                    f"组录取概率约 {round(g['group_prob'] * 100)}%",
                ]
                if g.get("special_type"):
                    reason_parts.append(f"类型：{g['special_type']}")
                if school.city:
                    reason_parts.append(f"位于{school.city}")
                reason = "；".join(reason_parts)
                risk_notes = []

            # 不再标注决策来源，全部由 LLM 或数据驱动

            items.append(RecommendationItem(
                group_index=idx,
                level=level,
                probability=round(g["group_prob"], 2),
                school_id=school.id,
                school_code=school.code,
                school_name=school.name,
                school_level=school.level,
                city=school.city,
                group_code=g["group_code"],
                majors=majors_out,
                year_breakdown=group_year_breakdown,
                reason=reason,
                risk_notes=risk_notes,
                data_confidence=g["confidence"],
            ))
        return items

    recommendations = _build_recommendation_items(ordered)
    special_recommendations = _build_recommendation_items(special_ordered)

    # 特殊类型按类型分组，便于前端展示
    special_by_type: Dict[str, List[Dict]] = {}
    for item in special_recommendations:
        # 从 majors 中取 special_type
        st = item.majors[0].get("special_type") if item.majors else "其他特殊类型"
        special_by_type.setdefault(st or "其他特殊类型", []).append(item.model_dump())

    warnings = []
    if special_recommendations and not allow_special:
        warnings.append(
            '检测到特殊类型招生计划，但用户未明确要求。'
            '如需查看，请在描述中提及"国家专项/中外合作/预科"等关键词。'
        )

    return {
        "profile": profile,
        "total_groups": len(recommendations),
        "冲_count": len(selected_冲),
        "稳_count": len(selected_稳),
        "保_count": len(selected_保),
        "recommendations": recommendations,
        "special_recommendations": special_recommendations,
        "special_by_type": special_by_type,
        "warnings": warnings,
        "llm_message": llm_msg,
    }
