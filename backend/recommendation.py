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
_SPECIAL_TYPE_KEYWORDS = [
    "预科", "国家专项", "地方专项", "高校专项", "定向",
    "民族班", "援藏", "南疆", "边防军人子女",
]


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

    # 只使用最新官方组线数据生成候选院校专业组
    latest_scores = (
        db.query(MajorScore)
        .join(Major)
        .join(School)
        .filter(
            MajorScore.province == province,
            MajorScore.subject_type == subject_type,
            MajorScore.year == LATEST_HISTORICAL_YEAR,
            MajorScore.group_lowest_rank.isnot(None),
        )
        .options(selectinload(MajorScore.major).selectinload(Major.school))
        .all()
    )

    # 按最新年份的组代码聚合专业
    group_map: Dict[Tuple[int, str], Dict] = {}
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

        # 过滤特殊类型
        if is_special_type(major.name, major.description) and not profile.allow_special_types:
            continue

        # 选科过滤
        req = major.subject_require or "不限"
        if not _subject_requirement_ok(subject_type, req, profile.preferred_major):
            continue

        group = group_map.setdefault(key, {
            "school": school,
            "group_code": f"{school.code}{gc.zfill(2)}",
            "subject_type": subject_type,
            "group_lowest_rank": ms.group_lowest_rank,
            "group_lowest_score": ms.group_lowest_score,
            "majors": [],
        })

        relevance = major_relevance_score(major.name, profile.preferred_major)
        prob = estimate_probability(profile.rank, ms.group_lowest_rank)
        group["majors"].append({
            "major": major,
            "probability": prob,
            "ref_rank": ms.group_lowest_rank,
            "ref_score": ms.group_lowest_score,
            "data_confidence": ms.data_confidence,
            "source": ms.data_source or "",
            "relevance": relevance,
            "year_breakdown": [{"year": ms.year, "rank": ms.group_lowest_rank, "score": ms.group_lowest_score, "confidence": ms.data_confidence}],
        })

    groups = []
    for g in group_map.values():
        if not g["majors"]:
            continue
        g["majors"].sort(key=lambda x: x["relevance"], reverse=True)
        top = g["majors"][:max_majors]
        # 组概率取组内最低（最保守）概率
        group_prob = min(i["probability"] for i in top)
        groups.append({
            "school": g["school"],
            "group_code": g["group_code"],
            "subject_type": g["subject_type"],
            "majors": top,
            "group_prob": group_prob,
            "confidence": "C",
            "avg_relevance": sum(i["relevance"] for i in top) / len(top),
        })

    # 按用户风险偏好分档
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

    冲 = [g for g in groups if 冲_min <= g["group_prob"] < 冲_max]
    稳 = [g for g in groups if 稳_min <= g["group_prob"] < 稳_max]
    保 = [g for g in groups if g["group_prob"] >= 保_min]

    # 排序：不再使用硬编码学校层次/城市权重，直接按录取概率与相关度排序
    def _sort_key(g: Dict) -> float:
        return g["group_prob"] * 10 + g["avg_relevance"] * 5

    冲.sort(key=_sort_key, reverse=True)
    稳.sort(key=_sort_key, reverse=True)
    保.sort(key=lambda g: g["group_prob"], reverse=True)

    # 目标数量：冲 10、稳 25、保 10
    target_冲, target_稳, target_保 = 10, 25, 10

    def _select_diverse(source: List[Dict], target: int, max_per_school: int = 2) -> List[Dict]:
        selected = []
        counts: Dict[int, int] = {}
        for g in source:
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

    ordered = selected_冲 + selected_稳 + selected_保

    recommendations = []
    for idx, g in enumerate(ordered, start=1):
        level = "冲" if g in selected_冲 else ("稳" if g in selected_稳 else "保")
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
            })

        # 数据驱动的推荐理由，不引入主观判断
        reason_parts = [
            f"{LATEST_HISTORICAL_YEAR}年官方投档位次 {g['majors'][0]['ref_rank']}",
            f"考生位次 {profile.rank}",
            f"组录取概率约 {round(g['group_prob'] * 100)}%",
        ]
        if school.city:
            reason_parts.append(f"位于{school.city}")

        recommendations.append(RecommendationItem(
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
            reason="；".join(reason_parts),
            risk_notes=[],
            data_confidence=g["confidence"],
        ))

    return {
        "profile": profile,
        "total_groups": len(recommendations),
        "冲_count": len(selected_冲),
        "稳_count": len(selected_稳),
        "保_count": len(selected_保),
        "recommendations": recommendations,
        "warnings": [],
    }
