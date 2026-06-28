import random
import re
from typing import List, Dict, Optional, Tuple
from sqlalchemy import and_
from sqlalchemy.orm import Session, selectinload, with_loader_criteria

from config import get_province_rule, default_rule
from config.province_rules import CURRENT_YEAR, LATEST_HISTORICAL_YEAR, DEFAULT_PLAN_YEAR
from models import Profile, School, Major, MajorScore, AdmissionPlan, RankTable
from schemas import RecommendationItem

try:
    from services.major_matcher import build_major_intent, score_major_relevance
except Exception:
    build_major_intent = None
    score_major_relevance = None


# ---------------------------------------------------------------------------
# 静态数据内存缓存：学校/专业/分数线/招生计划在运行期间基本不变，
# 第一次加载后 detach 出来供后续请求复用，避免每次请求都走 ORM 加载。
# ---------------------------------------------------------------------------
_schools_cache: Dict[Tuple[str, str], List[School]] = {}


def _load_schools_cached(db: Session, province: str, subject_type: str) -> List[School]:
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
# 专业热度偏移：从组线估算专业线时，根据专业名做 ±N 比例调整
# 位次越小越靠前；热门专业实际位次应比组线更靠前，冷门则更靠后。
# ---------------------------------------------------------------------------
_MAJOR_HEAT_OFFSETS = [
    # 热门：位次更靠前（乘以较小系数）
    (
        ["计算机", "软件", "人工智能", "数据科学", "大数据", "网络安全", "信息安全",
         "物联网", "电子信息", "通信", "电子科学", "微电子", "集成电路", "光电信息",
         "电气", "自动化", "机器人", "控制科学", "智能电网"],
        -0.12,
    ),
    # 中热/相关工科：小幅靠前
    (
        ["机械", "仪器", "测控", "新能源", "车辆", "航空航天", "船舶", "智能制造"],
        -0.05,
    ),
    # 冷门：位次更靠后（乘以较大系数）
    (
        ["土木", "化工", "材料", "生物", "环境", "采矿", "冶金", "地质", "海洋",
         "农业", "林业", "护理", "助产", "公共管理", "旅游管理", "酒店管理",
         "哲学", "社会学", "人类学", "考古"],
        +0.12,
    ),
]


def _heat_offset_ratio(major_name: str) -> float:
    name = major_name.lower()
    for keywords, ratio in _MAJOR_HEAT_OFFSETS:
        if any(kw in name for kw in keywords):
            return ratio
    return 0.0


def _apply_heat_offset(major_name: str, group_rank: int) -> int:
    if not group_rank or group_rank <= 0:
        return group_rank
    ratio = _heat_offset_ratio(major_name)
    # 热门 ratio<0 => rank 变小；冷门 ratio>0 => rank 变大
    adjusted = int(group_rank * (1.0 + ratio))
    return max(1, adjusted)


# ---------------------------------------------------------------------------
# 等位分换算：基于 RankTable 把位次映射为分数，再映射到目标年份位次
# ---------------------------------------------------------------------------
RankCache = Dict[int, List[Tuple[int, int]]]  # year -> [(score, accumulate), ...] sorted by score desc


def _build_rank_cache(db: Session, province: str, subject_type: str) -> RankCache:
    """预加载一分一段表到内存，按分数降序排列。"""
    cache: RankCache = {}
    rows = (
        db.query(RankTable)
        .filter(
            RankTable.province == province,
            RankTable.subject_type == subject_type,
            RankTable.accumulate is not None,
        )
        .order_by(RankTable.year, RankTable.score.desc())
        .all()
    )
    for r in rows:
        cache.setdefault(r.year, []).append((r.score, r.accumulate))
    return cache


def _score_for_rank_cached(cache: RankCache, year: int, rank: int) -> Optional[int]:
    """根据一分一段表把位次反查为分数；无精确匹配时线性插值。"""
    rows = cache.get(year)
    if not rows:
        return None
    for i, (score, acc) in enumerate(rows):
        if acc <= rank:
            if i == 0:
                return score
            prev_score, prev_acc = rows[i - 1]
            if prev_acc != acc:
                ratio = (rank - acc) / (prev_acc - acc)
                return int(score + ratio * (prev_score - score))
            return score
    # 位次比最差还差，返回最低分
    return rows[-1][0]


def _rank_for_score_cached(cache: RankCache, year: int, score: int) -> Optional[int]:
    """根据一分一段表把分数换算为位次；无精确匹配时线性插值。"""
    rows = cache.get(year)
    if not rows:
        return None
    # rows sorted by score desc
    for i, (sc, acc) in enumerate(rows):
        if sc == score:
            return acc
        if sc < score:
            # previous row has higher score
            if i == 0:
                return acc
            upper_score, upper_acc = rows[i - 1]
            lower_score, lower_acc = sc, acc
            if upper_score == lower_score:
                return upper_acc
            ratio = (score - lower_score) / (upper_score - lower_score)
            return int(lower_acc + ratio * (upper_acc - lower_acc))
    # score lower than all
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
    """
    把 from_year 的考生位次换算为 to_year 的等效位次。
    实现：candidate_rank -> from_year 等位分 -> to_year 位次。
    若缺少 from_year 一分一段表，则退而用 candidate_score 直接查 to_year 位次。
    若均不可行，返回原始 candidate_rank（降级但不崩溃）。
    """
    if from_year == to_year:
        return candidate_rank

    if rank_cache is None and db is not None:
        rank_cache = _build_rank_cache(db, province, subject_type)
    if rank_cache is None:
        return candidate_rank

    equivalent_score = _score_for_rank_cached(rank_cache, from_year, candidate_rank)

    if equivalent_score is None and candidate_score is not None:
        equivalent_score = candidate_score

    if equivalent_score is not None:
        to_rank = _rank_for_score_cached(rank_cache, to_year, equivalent_score)
        if to_rank is not None:
            return to_rank

    return candidate_rank


# ---------------------------------------------------------------------------
# 专业线优先 + 组线估算
# ---------------------------------------------------------------------------
SiblingCache = Dict[Tuple[int, str, str, int], Tuple[int, Optional[int]]]


def _build_sibling_cache(
    group_majors_map: Dict[Tuple[int, str, str], List[Major]],
    province: str,
    subject_type: str,
) -> SiblingCache:
    """
    预计算每个院校专业组 + 年份的同组真实专业线均值（confidence B）。
    返回: {(school_id, group_code, subject_type, year): (avg_rank, avg_score)}
    """
    cache: SiblingCache = {}
    for (school_id, group_code, st), majors in group_majors_map.items():
        # 先按年份聚合所有非自身真实专业线
        year_ranks: Dict[int, List[int]] = {}
        year_scores: Dict[int, List[int]] = {}
        for gm in majors:
            for gs in gm.scores:
                if (
                    gs.province == province
                    and gs.subject_type == subject_type
                    and gs.year is not None
                    and gs.major_lowest_rank is not None
                ):
                    year_ranks.setdefault(gs.year, []).append(gs.major_lowest_rank)
                    if gs.major_lowest_score is not None:
                        year_scores.setdefault(gs.year, []).append(gs.major_lowest_score)
        for year, ranks in year_ranks.items():
            avg_rank = int(sum(ranks) / len(ranks))
            scores = year_scores.get(year, [])
            avg_score = int(sum(scores) / len(scores)) if scores else None
            cache[(school_id, group_code, st, year)] = (avg_rank, avg_score)
    return cache


def _resolve_major_rank_for_year(
    major: Major,
    score: MajorScore,
    group_majors: Optional[List[Major]],
    sibling_cache: Optional[SiblingCache] = None,
) -> Tuple[Optional[int], Optional[int], str]:
    """
    返回某一年度针对该专业的最佳可用 (rank, score, confidence)。
    优先级：A 专业真实线 -> B 同组专业线均值 -> C 组线热度偏移估算 -> D 缺失。
    """
    # A: 专业自身录取线
    if score.major_lowest_rank is not None:
        return score.major_lowest_rank, score.major_lowest_score, "A"

    # B: 同专业组其他有专业线的均值（优先查预计算缓存）
    if sibling_cache is not None and group_majors:
        key = (
            group_majors[0].school_id if group_majors else None,
            major.group_code or "01",
            score.subject_type,
            score.year,
        )
        # school_id 可能为 None（理论上不会），退回到遍历
        if key[0] is not None and key in sibling_cache:
            return sibling_cache[key][0], sibling_cache[key][1], "B"

    if group_majors:
        sibling_ranks = []
        sibling_scores = []
        for gm in group_majors:
            if gm.id == major.id:
                continue
            for gs in gm.scores:
                if (
                    gs.year == score.year
                    and gs.province == score.province
                    and gs.subject_type == score.subject_type
                    and gs.major_lowest_rank is not None
                ):
                    sibling_ranks.append(gs.major_lowest_rank)
                    if gs.major_lowest_score is not None:
                        sibling_scores.append(gs.major_lowest_score)
        if sibling_ranks:
            avg_rank = int(sum(sibling_ranks) / len(sibling_ranks))
            avg_score = int(sum(sibling_scores) / len(sibling_scores)) if sibling_scores else None
            return avg_rank, avg_score, "B"

    # C: 组线反推 + 专业热度偏移
    if score.group_lowest_rank is not None:
        est_rank = _apply_heat_offset(major.name, score.group_lowest_rank)
        return est_rank, score.group_lowest_score, "C"

    # D: 仅有 lowest_rank 但无法判断来源（兼容旧数据）
    if score.lowest_rank is not None:
        return score.lowest_rank, score.lowest_score, "C"

    return None, None, "D"


def get_major_latest_score(
    major: Major,
    province: str,
    subject_type: str,
    db: Optional[Session] = None,
    candidate_score: Optional[int] = None,
    group_majors: Optional[List[Major]] = None,
    rank_cache: Optional[RankCache] = None,
    sibling_cache: Optional[SiblingCache] = None,
) -> Optional[Dict]:
    """
    获取专业最新一年的有效录取数据。
    优先专业真实线，其次同组插值，再次组线热度估算。
    返回含等位分换算后位次、置信等级、多年加权信息的字典。
    """
    scores = [
        s for s in major.scores
        if s.province == province and s.subject_type == subject_type and s.year is not None
    ]
    if not scores:
        return None

    # 按年份降序，计算每年的最佳可用位次
    year_resolved = []
    for s in sorted(scores, key=lambda x: x.year, reverse=True):
        rank, score, conf = _resolve_major_rank_for_year(major, s, group_majors, sibling_cache=sibling_cache)
        if rank is not None:
            year_resolved.append((s.year, rank, score, conf, s))

    if not year_resolved:
        return None

    # 近三年加权平均（2024 权重最高）
    weights = {2024: 0.50, 2023: 0.30, 2022: 0.20}
    total_w = sum(weights.get(y, 0.10) for y, _, _, _, _ in year_resolved)
    if total_w <= 0:
        total_w = 1.0

    # 等位分换算：把历史位次换算到当前志愿填报年份
    if rank_cache is None and db is not None:
        rank_cache = _build_rank_cache(db, province, subject_type)
    converted_ranks = []
    for year, rank, score, conf, s in year_resolved:
        if rank_cache is not None:
            equiv_rank = rank_to_equivalent(
                candidate_rank=rank,
                from_year=year,
                to_year=CURRENT_YEAR,
                province=province,
                subject_type=subject_type,
                rank_cache=rank_cache,
                candidate_score=candidate_score,
            )
        else:
            equiv_rank = rank
        converted_ranks.append((year, equiv_rank, score, conf, s))

    weighted_rank = int(
        sum(equiv_rank * weights.get(year, 0.10) for year, equiv_rank, _, _, _ in converted_ranks)
        / total_w
    )

    latest = converted_ranks[0]
    latest_year, latest_rank, latest_score, latest_conf, latest_score_obj = latest

    return {
        "year": latest_year,
        "lowest_rank": weighted_rank,
        "latest_rank": latest_rank,
        "lowest_score": latest_score,
        "avg_score": latest_score_obj.avg_score,
        "confidence": latest_conf,
        "source": latest_score_obj.data_source or "",
        "year_breakdown": [
            {"year": y, "rank": r, "score": sc, "confidence": c}
            for y, r, sc, c, _ in converted_ranks
        ],
    }


# ---------------------------------------------------------------------------
# 招生计划
# ---------------------------------------------------------------------------
def _precompute_group_plan_counts(db: Session, province: str, subject_type: str) -> Dict[Tuple[int, str], int]:
    """一次性汇总所有院校专业组的招生计划（优先 2026，无则回退 2025）。"""
    counts: Dict[Tuple[int, str], int] = {}
    # 尝试当前年份
    rows = (
        db.query(Major.school_id, Major.group_code, AdmissionPlan.plan_count)
        .join(AdmissionPlan, AdmissionPlan.major_id == Major.id)
        .filter(
            AdmissionPlan.province == province,
            AdmissionPlan.subject_type == subject_type,
            AdmissionPlan.year == DEFAULT_PLAN_YEAR,
        )
        .all()
    )
    for school_id, group_code, plan_count in rows:
        key = (school_id, group_code or "01")
        counts[key] = counts.get(key, 0) + (plan_count or 0)

    # 回退到历史年份补充缺失的组
    missing_keys = None
    if DEFAULT_PLAN_YEAR != LATEST_HISTORICAL_YEAR:
        existing_keys = set(counts.keys())
        rows_hist = (
            db.query(Major.school_id, Major.group_code, AdmissionPlan.plan_count)
            .join(AdmissionPlan, AdmissionPlan.major_id == Major.id)
            .filter(
                AdmissionPlan.province == province,
                AdmissionPlan.subject_type == subject_type,
                AdmissionPlan.year == LATEST_HISTORICAL_YEAR,
            )
            .all()
        )
        for school_id, group_code, plan_count in rows_hist:
            key = (school_id, group_code or "01")
            if key not in existing_keys:
                counts[key] = counts.get(key, 0) + (plan_count or 0)
    return counts


def get_group_plan_count(
    school_id: int,
    group_code: str,
    province: str,
    subject_type: str,
    db: Session,
    year: int = DEFAULT_PLAN_YEAR,
) -> int:
    """汇总院校专业组当年招生计划人数；无当前年份数据时回退到最新历史年份。"""
    total = (
        db.query(AdmissionPlan)
        .join(Major, AdmissionPlan.major_id == Major.id)
        .filter(
            Major.school_id == school_id,
            Major.group_code == group_code,
            AdmissionPlan.province == province,
            AdmissionPlan.subject_type == subject_type,
            AdmissionPlan.year == year,
        )
        .with_entities(AdmissionPlan.plan_count)
        .all()
    )
    count = sum(p[0] for p in total if p[0])
    if count == 0 and year != LATEST_HISTORICAL_YEAR:
        return get_group_plan_count(
            school_id, group_code, province, subject_type, db, year=LATEST_HISTORICAL_YEAR
        )
    return count


# ---------------------------------------------------------------------------
# 录取概率
# ---------------------------------------------------------------------------
def estimate_probability(candidate_rank: int, ref_rank: int, plan_count: int, trend: float = 0.0) -> float:
    """基于位次差距与招生计划，估算录取概率。"""
    if ref_rank <= 0:
        return 0.5
    rank_ratio = candidate_rank / ref_rank
    # ratio < 1 表示考生位次更靠前，概率更高
    base = 1.0 / (1.0 + max(0, rank_ratio - 0.85) * 4.0)
    # 计划越多越稳
    plan_boost = min(0.1, plan_count / 200.0)
    # 趋势：正值表示热门上升，概率下调
    trend_penalty = max(-0.15, min(0.15, trend))
    prob = base + plan_boost - trend_penalty
    return max(0.02, min(0.99, prob))


# ---------------------------------------------------------------------------
# 专业语义匹配（基于 LLM 一次性扩展 + 本地打分）
# ---------------------------------------------------------------------------
# 缓存用户 LLM 意向扩展结果，避免对每专业重复调用 LLM
_intent_cache: Dict[str, Dict] = {}


def major_relevance_score(major_name: str, preferred_majors: Optional[str]) -> float:
    """
    评估专业名称与考生意向的相关度，返回 0-1 分数。
    完全基于 services.major_matcher：LLM 扩展意向词表后本地快速打分。
    """
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
    """
    增强选科过滤：
    - 物理类考生，专业组要求含“化”或“物化”时，必须考生选科含化学（默认物理类考生含物化，
      但最好从文本推断）。
    - 历史类考生，专业组要求含“物”时排除。
    """
    req = (require or "不限").strip()
    if req == "不限":
        return True

    if subject_type == "历史":
        return "物" not in req

    # 物理类
    if "物" not in req and "化" not in req and "生" not in req:
        # 仍然允许（可能是文科专业在历史类不招生，但物理类考生可报不限科目专业）
        return True

    # 如果专业要求化学，默认接受；若文本明确说“没选化学/不含化学/化学生物没选”等才排除
    if "化" in req and profile_text:
        if re.search(r"没选化学|不含化学|化学.{0,3}没选|没.{0,2}化学", profile_text):
            return False

    return True


# ---------------------------------------------------------------------------
# 策略分
# ---------------------------------------------------------------------------
def strategy_score(school: School, major: Major, profile: Profile) -> float:
    """根据用户策略给候选打分，用于同档位排序。"""
    score = 0.0
    strategy = profile.strategy

    if strategy == "school":
        level_weight = {"985": 100, "211": 80, "双一流": 60, "普通本科": 30, "民办本科": 15, None: 20}
        score += level_weight.get(school.level, 20) * 2
        score += (10 if school.has_phd else 0) + (5 if school.has_master else 0)
    elif strategy == "major":
        eval_weight = {"A+": 100, "A": 85, "A-": 70, "B+": 55, "B": 45, "B-": 35, "C+": 25, "C": 20, None: 10}
        score += eval_weight.get(major.discipline_eval, 10) * 2
        score += major.employment_score * 10
    elif strategy == "city":
        preferred = profile.preferred_city or ""
        if school.city and school.city in preferred:
            score += 100
        tier = {"北京": 90, "上海": 90, "广州": 80, "深圳": 80, "杭州": 75, "南京": 75, "武汉": 70, "成都": 65}
        score += tier.get(school.city, 40)
    elif strategy == "employment":
        score += major.employment_score * 20
        if major.category in ["工科", "医科"]:
            score += 20
    elif strategy == "academic":
        score += (10 if school.has_phd else 0) + (5 if school.has_master else 0)
        eval_weight = {"A+": 100, "A": 85, "A-": 70, "B+": 55, "B": 45}
        score += eval_weight.get(major.discipline_eval, 20)
    else:  # balanced
        level_weight = {"985": 50, "211": 40, "双一流": 30, "普通本科": 15, "民办本科": 8, None: 10}
        eval_weight = {"A+": 50, "A": 40, "A-": 30, "B+": 20, "B": 15, None: 5}
        score += level_weight.get(school.level, 10)
        score += eval_weight.get(major.discipline_eval, 5)
        score += major.employment_score * 5
        if school.city and profile.preferred_city and school.city in profile.preferred_city:
            score += 20

    return score


# ---------------------------------------------------------------------------
# 大类招生检测
# ---------------------------------------------------------------------------
def _is_broad_category(major_name: str) -> bool:
    return any(kw in major_name for kw in ["试验班", "大类", "卓越班", "创新班"])


# ---------------------------------------------------------------------------
# 主推荐流程
# ---------------------------------------------------------------------------
def build_recommendation(profile: Profile, db: Session) -> Dict:
    province = profile.province or "湖北"
    subject_type = profile.subject_type
    rules = get_province_rule(province) or default_rule()
    warnings = []

    max_groups = rules.get("max_groups", 45)
    max_majors = rules.get("max_majors_per_group", 6)

    # 拉取所有学校和专业（优先使用内存缓存）
    schools = _load_schools_cached(db, province, subject_type)
    candidates = []

    # 预处理：按院校专业组聚合专业，并预加载一分一段表缓存
    group_majors_map: Dict[Tuple[int, str, str], List[Major]] = {}
    for school in schools:
        for major in school.majors:
            key = (school.id, major.group_code or "01", subject_type)
            group_majors_map.setdefault(key, []).append(major)

    rank_cache = _build_rank_cache(db, province, subject_type)

    # 预计算所有专业组招生计划，避免循环中反复查询
    plan_counts = _precompute_group_plan_counts(db, province, subject_type)

    # 预计算同组专业线均值，避免对每个专业重复遍历同组所有专业
    sibling_cache = _build_sibling_cache(group_majors_map, province, subject_type)

    for school in schools:
        for major in school.majors:
            # 过滤特殊类型招生
            notes = major.description or ""
            if is_special_type(major.name, notes) and not profile.allow_special_types:
                continue

            # 选科匹配增强
            req = major.subject_require or "不限"
            if not _subject_requirement_ok(subject_type, req, profile.preferred_major):
                continue

            # 历史类考生若专业要求物理则排除（兜底）
            if subject_type == "历史" and "物" in req:
                continue

            key = (school.id, major.group_code or "01", subject_type)
            group_majors = group_majors_map.get(key, [])

            data = get_major_latest_score(
                major,
                province,
                subject_type,
                db=db,
                candidate_score=profile.score if profile.score > 0 else None,
                group_majors=group_majors,
                rank_cache=rank_cache,
                sibling_cache=sibling_cache,
            )
            if data is None:
                continue

            plan_count = plan_counts.get((school.id, major.group_code or "01"), 0)
            prob = estimate_probability(
                candidate_rank=profile.rank,
                ref_rank=data["lowest_rank"],
                plan_count=plan_count,
            )

            relevance = major_relevance_score(major.name, profile.preferred_major)

            candidates.append({
                "school": school,
                "major": major,
                "probability": prob,
                "ref_rank": data["lowest_rank"],
                "ref_score": data["lowest_score"],
                "confidence": data["confidence"],
                "source": data.get("source", ""),
                "strategy_score": strategy_score(school, major, profile),
                "relevance": relevance,
                "year_breakdown": data.get("year_breakdown", []),
            })

    # 按院校专业组聚合
    group_map: Dict[Tuple[int, str, str], List[Dict]] = {}
    seen_major_names: Dict[Tuple[int, str, str, str], bool] = {}
    for c in candidates:
        key = (c["school"].id, c["major"].group_code or "01", subject_type)
        # 同学校同专业组去重同名专业
        dup_key = (c["school"].id, c["major"].group_code or "01", subject_type, c["major"].name)
        if seen_major_names.get(dup_key):
            continue
        seen_major_names[dup_key] = True
        group_map.setdefault(key, []).append(c)

    # 组内排序与聚合
    groups = []
    for (school_id, group_code, st), items in group_map.items():
        school = items[0]["school"]
        plan_count = plan_counts.get((school_id, group_code or "01"), 0)

        # 组内排序：相关度 0.5 + 概率 0.3 + 学科评估 0.2
        def _in_group_score(item: Dict) -> float:
            eval_weight = {"A+": 1.0, "A": 0.9, "A-": 0.8, "B+": 0.7, "B": 0.6, "B-": 0.5, "C+": 0.4, "C": 0.3, None: 0.1}
            discipline = eval_weight.get(item["major"].discipline_eval, 0.1)
            return item["relevance"] * 0.5 + item["probability"] * 0.3 + discipline * 0.2

        items.sort(key=_in_group_score, reverse=True)
        top6 = items[:max_majors]
        group_prob = min(i["probability"] for i in top6)
        # 组置信度取最低
        conf_order = {"A": 4, "B": 3, "C": 2, "D": 1}
        avg_conf = min((i["confidence"] for i in top6), key=lambda x: conf_order.get(x, 0))

        groups.append({
            "school": school,
            "group_code": group_code,
            "subject_type": st,
            "majors": top6,
            "group_prob": group_prob,
            "confidence": avg_conf,
            "plan_count": plan_count,
            "avg_relevance": sum(i["relevance"] for i in top6) / len(top6),
            "has_broad_category": any(_is_broad_category(i["major"].name) for i in top6),
        })

    # 按概率分档
    冲 = [g for g in groups if 0.20 <= g["group_prob"] < 0.50]
    稳 = [g for g in groups if 0.50 <= g["group_prob"] < 0.85]
    保 = [g for g in groups if g["group_prob"] >= 0.85]

    # 各档内部按策略分 + 专业相关度综合排序
    def _group_sort_key(g: Dict) -> float:
        avg_strategy = sum(i["strategy_score"] for i in g["majors"]) / len(g["majors"])
        # major 策略下相关度权重更高；school/city 策略下学校/城市权重更高
        if profile.strategy == "major":
            return g["avg_relevance"] * 80 + avg_strategy * 0.4
        elif profile.strategy == "school":
            return avg_strategy + g["avg_relevance"] * 20
        else:
            return avg_strategy * 0.5 + g["avg_relevance"] * 40 + g["group_prob"] * 10

    冲.sort(key=_group_sort_key, reverse=True)
    稳.sort(key=_group_sort_key, reverse=True)

    # 保底志愿：真正保底
    def _bao_score(g: Dict) -> float:
        school = g["school"]
        score = 0.0
        # 湖北省内 / 省会城市公办 优先
        if school.province == province:
            score += 30
        if school.city in ["武汉", "北京", "上海", "广州", "深圳", "杭州", "南京", "成都"]:
            score += 15
        if school.is_public:
            score += 20
        # 招生计划多
        score += min(15, g["plan_count"] / 10)
        # 位次显著低于考生更稳（ratio 越小越安全）
        min_ref = min(i["ref_rank"] for i in g["majors"] if i["ref_rank"])
        if min_ref and min_ref > 0:
            ratio = profile.rank / min_ref
            if ratio <= 0.6:
                score += 25
            elif ratio <= 0.8:
                score += 10
        # 专业相关性可接受
        score += g["avg_relevance"] * 20
        # 避免跨省偏远 211 的冷门专业
        if school.level in ["211", "985"] and school.province != province:
            score -= 15
        return score

    保.sort(key=_bao_score, reverse=True)

    # 学校去重：同档同校最多保留 2 个专业组
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

    # 目标数量：冲 10、稳 25、保 10，共 45
    target_冲, target_稳, target_保 = 10, 25, 10
    selected_冲 = _select_diverse(冲, target_冲)
    selected_稳 = _select_diverse(稳, target_稳)
    selected_保 = _select_diverse(保, target_保)

    # 若保底不足，尝试从稳档补位（放宽到概率 70% 以上且位次比显著安全）
    if len(selected_保) < 5:
        supplemental = [
            g for g in 稳
            if g["group_prob"] >= 0.70
            and any(i["ref_rank"] and profile.rank / i["ref_rank"] <= 0.7 for i in g["majors"])
        ]
        supplemental.sort(key=_bao_score, reverse=True)
        needed = 5 - len(selected_保)
        selected_保 += supplemental[:needed]
        if supplemental[:needed]:
            warnings.append("保底志愿数量偏少，已从稳妥档补充部分安全志愿。")

    if len(selected_保) < 5:
        warnings.append("保底志愿数量偏少，建议扩大院校范围或降低保底预期，避免滑档风险。")
    if len(selected_稳) < 15:
        warnings.append("稳妥志愿数量不足，志愿结构 risky。")

    ordered = selected_冲 + selected_稳 + selected_保

    # 生成最终推荐结构
    recommendations = []
    for idx, g in enumerate(ordered, start=1):
        level = "冲" if g in selected_冲 else ("稳" if g in selected_稳 else "保")
        school = g["school"]
        majors_out = []
        risk_notes = []
        low_conf = False
        any_low_relevance = False

        for item in g["majors"]:
            m = item["major"]
            majors_out.append({
                "major_id": m.id,
                "name": m.name,
                "category": m.category,
                "discipline_eval": m.discipline_eval,
                "probability": round(item["probability"], 2),
                "ref_rank": item["ref_rank"],
                "ref_score": item["ref_score"],
                "data_confidence": item["confidence"],
                "relevance": round(item["relevance"], 2),
            })
            if item["confidence"] in ("C", "D"):
                low_conf = True
            if item["relevance"] < 0.4:
                any_low_relevance = True

        # 风险提示
        if level == "冲" and any_low_relevance:
            risk_notes.append("组内多为非目标专业，被调剂风险高")
        if g["has_broad_category"]:
            risk_notes.append("大类招生/试验班，具体专业需入校后分流")
        if low_conf:
            risk_notes.append("历史数据为估算/缺失（置信 C/D），建议人工核实")
        if level == "冲":
            low_prob_majors = [i["major"].name for i in g["majors"] if i["probability"] < 0.35]
            if low_prob_majors:
                risk_notes.append(f"{'、'.join(low_prob_majors[:2])} 等录取概率较低")

        # 推荐理由真实化
        reason_parts = []
        if school.level:
            reason_parts.append(f"{school.level}院校")
        if school.city:
            reason_parts.append(f"位于{school.city}")

        if g["avg_relevance"] >= 0.6:
            reason_parts.append("专业组含计算机/电子信息方向，与意向匹配")
        elif g["avg_relevance"] >= 0.3:
            reason_parts.append("专业组以工科试验班/大类招生为主，需入学后分流，部分方向相关")
        else:
            top_cat = g["majors"][0]["major"].category or "其他"
            reason_parts.append(f"该组以{top_cat}门类为主，与意向关联较弱，建议谨慎；若接受调剂可考虑")

        # 数据来源与置信度
        conf_desc = {
            "A": "A（专业真实线）",
            "B": "B（同组专业线插值）",
            "C": "C（组线反推/估算）",
            "D": "D（数据缺失）",
        }
        reason_parts.append(f"数据置信 {conf_desc.get(g['confidence'], g['confidence'])}")
        reason_parts.append(f"基于 {g['majors'][0].get('source', '官方数据')}")

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
            reason="，".join(reason_parts),
            risk_notes=risk_notes,
            data_confidence=g["confidence"],
        ))

    result = {
        "profile": profile,
        "total_groups": len(recommendations),
        "冲_count": len(selected_冲),
        "稳_count": len(selected_稳),
        "保_count": len(selected_保),
        "recommendations": recommendations,
        "warnings": warnings,
    }
    return result
