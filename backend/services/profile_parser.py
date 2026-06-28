"""
Free-text profile parser for Spiral.
Turns a user's natural-language description + province rank into a structured Profile.
No presets: the user can speak freely.

High-quality middle process:
1. Try LLM parsing when WINCODE_API_KEY is available.
2. Validate & fallback to deterministic regex/heuristic parser.
3. Return structured ProfileCreate with transparent explanations.
"""

import os
import re
from typing import Dict, List, Optional
from schemas import ProfileCreate
from services.llm_service import parse_profile_with_llm


# Keywords that signal each strategy
_STRATEGY_KEYWORDS = {
    "school": ["学校优先", "院校优先", "冲学校", "冲院校", "名校", "层次", "title", "牌子", "985", "211"],
    "major": ["专业优先", "冲专业", "好专业", "专业壁垒", "想学", "感兴趣", "兴趣", "爱好"],
    "city": ["城市优先", "地域优先", "想去", "留在", "武汉", "北京", "上海", "广州", "深圳", "杭州", "南京", "成都"],
    "employment": ["就业优先", "好就业", "赚钱", "薪资", "工资", "找工作", "就业率", "考公", "编制"],
    "academic": ["升学优先", "考研", "保研", "深造", "读博", "研究", "学术"],
}

_CITY_LIST = [
    "北京", "上海", "广州", "深圳", "杭州", "南京", "武汉", "成都", "西安", "重庆",
    "天津", "苏州", "长沙", "郑州", "青岛", "大连", "厦门", "宁波", "无锡", "合肥",
    "济南", "福州", "昆明", "南昌", "贵阳", "海口", "兰州", "太原", "石家庄", "沈阳",
    "长春", "哈尔滨", "南宁", "呼和浩特", "乌鲁木齐", "拉萨", "银川", "西宁",
]

_SUBJECT_KEYWORDS = {
    "物理": ["物理", "物化", "理科", "物理类", "物化生", "物化地", "物化政"],
    "历史": ["历史", "史政地", "文科", "历史类", "史政生", "史地化", "史地"],
}

_MAJOR_CATEGORIES = [
    "计算机", "软件工程", "电子信息", "通信工程", "电气工程", "自动化", "机械",
    "土木工程", "建筑学", "临床医学", "口腔医学", "医学", "护理", "药学",
    "法学", "汉语言文学", "新闻", "外语", "英语", "会计", "金融", "经济", "管理",
    "数学", "物理", "化学", "生物", "地理", "政治", "历史",
]


def _detect_strategy(text: str) -> str:
    text = text.lower()
    scores = {k: 0 for k in _STRATEGY_KEYWORDS}
    for strategy, keywords in _STRATEGY_KEYWORDS.items():
        for kw in keywords:
            scores[strategy] += text.count(kw.lower())
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "balanced"


def _detect_subject_type(text: str) -> Optional[str]:
    text = text.lower()
    scores = {k: 0 for k in _SUBJECT_KEYWORDS}
    for st, keywords in _SUBJECT_KEYWORDS.items():
        for kw in keywords:
            scores[st] += text.count(kw.lower())
    if scores["物理"] == scores["历史"] == 0:
        return None
    return "物理" if scores["物理"] >= scores["历史"] else "历史"


def _detect_cities(text: str) -> Optional[str]:
    found = [c for c in _CITY_LIST if c in text]
    return "、".join(found) if found else None


def _detect_preferred_majors(text: str) -> Optional[str]:
    found = [m for m in _MAJOR_CATEGORIES if m in text]
    return "、".join(found) if found else None


def _detect_score(text: str) -> Optional[int]:
    patterns = [
        r"(\d{3})\s*分",
        r"(?:考|分数|成绩|总分)[^\d]*(\d{3})",
        r"(\d{3})\s*分?\s*左右",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            score = int(m.group(1))
            if 300 <= score <= 750:
                return score
    return None


def _detect_rank(text: str, provided_rank: Optional[int] = None) -> int:
    if provided_rank is not None:
        return provided_rank
    patterns = [
        r"排名\s*(\d+)",
        r"位次\s*(\d+)",
        r"省排\s*(\d+)",
        r"全省\s*(\d+)",
        r"(\d+)\s*名",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            rank = int(m.group(1))
            if rank > 0:
                return rank
    raise ValueError("未能从文本中识别出省排名，请明确提供位次。")


def _detect_adjustment(text: str) -> bool:
    # 默认所有考生均服从调剂；不识别文本中的“不服从”描述
    return True


def _detect_special_types(text: str) -> bool:
    """仅当用户文本明确愿意接受特殊类型招生时才允许推荐。"""
    pattern = r"(?:接受|愿意|可以|填报|报|考虑|走).{0,5}(国家专项|地方专项|高校专项|预科|定向|民族班|援藏|南疆|边防军人子女)"
    # 同时排除明确拒绝的上下文
    negative = re.search(r"(?:不要|不想|不填|不接受|拒绝|排除).{0,5}(国家专项|地方专项|高校专项|预科|定向|民族班|援藏|南疆|边防军人子女)", text)
    if negative:
        return False
    return bool(re.search(pattern, text))


def _detect_province(text: str) -> Optional[str]:
    provinces = [
        "北京", "天津", "上海", "重庆",
        "河北", "山西", "辽宁", "吉林", "黑龙江",
        "江苏", "浙江", "安徽", "福建", "江西", "山东",
        "河南", "湖北", "湖南", "广东", "海南",
        "四川", "贵州", "云南", "陕西", "甘肃", "青海",
        "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
    ]
    for p in provinces:
        if p in text:
            return p
    return None


def _rule_based_parse(text: str, rank: Optional[int] = None, province: Optional[str] = None) -> ProfileCreate:
    """Deterministic parser used as fallback / validation."""
    detected_rank = _detect_rank(text, rank)
    score = _detect_score(text)
    detected_province = _detect_province(text) or province
    detected_subject = _detect_subject_type(text) or "物理"
    return ProfileCreate(
        name="考生",
        province=detected_province or "湖北",
        subject_type=detected_subject,
        score=score if score is not None else 0,
        rank=detected_rank,
        preferred_major=_detect_preferred_majors(text),
        preferred_city=_detect_cities(text),
        strategy=_detect_strategy(text),
        accept_adjustment=True,
        allow_special_types=_detect_special_types(text),
    )


def parse_free_text(text: str, rank: Optional[int] = None, province: Optional[str] = None) -> ProfileCreate:
    """
    Parse free-text description + optional rank into a ProfileCreate schema.
    Uses LLM when API key is available; always validates with rule-based fallback.
    Raises ValueError if rank cannot be determined.
    """
    text = text.strip()
    if not text:
        raise ValueError("描述不能为空。")

    fallback = _rule_based_parse(text, rank, province=province)

    if not os.environ.get("WINCODE_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        return fallback

    try:
        llm_data = parse_profile_with_llm(text, rank)
        # Merge LLM output with fallback for missing/invalid fields
        if not llm_data.get("rank"):
            llm_data["rank"] = fallback.rank
        if not llm_data.get("subject_type") in ("物理", "历史"):
            llm_data["subject_type"] = fallback.subject_type
        if llm_data.get("strategy") not in ("school", "major", "city", "employment", "academic", "balanced"):
            llm_data["strategy"] = fallback.strategy
        if not llm_data.get("province"):
            llm_data["province"] = fallback.province
        if llm_data.get("score") is None:
            llm_data["score"] = fallback.score
        # 强制默认服从调剂，不依赖 LLM 识别该字段
        llm_data["accept_adjustment"] = True
        if not isinstance(llm_data.get("allow_special_types"), bool):
            llm_data["allow_special_types"] = fallback.allow_special_types

        return ProfileCreate(
            name="考生",
            province=llm_data["province"],
            subject_type=llm_data["subject_type"],
            score=int(llm_data["score"]),
            rank=int(llm_data["rank"]),
            preferred_major=llm_data.get("preferred_major") or fallback.preferred_major,
            preferred_city=llm_data.get("preferred_city") or fallback.preferred_city,
            strategy=llm_data["strategy"],
            accept_adjustment=True,
            allow_special_types=bool(llm_data.get("allow_special_types", fallback.allow_special_types)),
        )
    except Exception as e:
        # Never fail the whole request because LLM is unavailable/returns bad JSON
        print(f"[profile_parser] LLM parse failed ({e}), using rule-based fallback.")
        return fallback


def explain_parsing(profile: ProfileCreate, original_text: str, source: str = "规则解析") -> List[Dict]:
    """Return human-readable parsing steps for transparency."""
    explanations = []
    explanations.append({
        "item": "省份",
        "value": profile.province,
        "reason": "从描述中识别到省份关键词" if profile.province in original_text else "默认使用湖北规则",
    })
    explanations.append({
        "item": "科类",
        "value": profile.subject_type,
        "reason": "根据选科/文理科关键词推断",
    })
    explanations.append({
        "item": "位次",
        "value": str(profile.rank),
        "reason": "用户提供或从文本中提取",
    })
    if profile.score and profile.score > 0:
        explanations.append({
            "item": "分数",
            "value": str(profile.score),
            "reason": "从文本中提取",
        })
    explanations.append({
        "item": "填报策略",
        "value": profile.strategy,
        "reason": f"根据描述中的优先级关键词判断（{source}）",
    })
    if profile.preferred_major:
        explanations.append({
            "item": "意向专业",
            "value": profile.preferred_major,
            "reason": "从描述中识别",
        })
    if profile.preferred_city:
        explanations.append({
            "item": "意向城市",
            "value": profile.preferred_city,
            "reason": "从描述中识别",
        })
    explanations.append({
        "item": "服从调剂",
        "value": "是",
        "reason": "系统默认所有考生服从专业组内调剂",
    })
    explanations.append({
        "item": "特殊类型招生",
        "value": "允许" if profile.allow_special_types else "排除",
        "reason": "仅在文本明确提及国家专项/预科/定向等时才允许" if profile.allow_special_types else "默认排除预科、专项、定向等特殊类型招生",
    })
    return explanations
