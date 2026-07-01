"""
Major semantic matching for Spiral.

专业意向扩展用纯规则分词（不调 LLM，省一轮 LLM 配额）。
专业相关度打分也用关键词匹配，LLM 综合决策时拿到用户原文自行判断。
"""

import re
from typing import List, Dict, Optional, Tuple


_NORMALIZE_RE = re.compile(r"[\s\/\(\)（）]+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.lower())


def build_major_intent(preferred_major_text: Optional[str]) -> Dict:
    """
    纯规则分词扩展：把用户意向专业文本拆成关键词列表。
    不做 LLM 扩展（LLM 综合决策时会拿到用户原文自行理解）。
    """
    if not preferred_major_text:
        return {"raw": "", "keywords": [], "categories": []}

    raw = preferred_major_text.strip()
    keywords = set()
    for token in re.split(r"[、,，；;|/]", raw):
        token = token.strip()
        if token:
            keywords.add(token)

    return {
        "raw": raw,
        "keywords": sorted(keywords),
        "categories": [],
    }


def score_major_relevance(major_name: str, major_category: Optional[str], intent: Dict) -> Tuple[float, str]:
    """
    Score how relevant a major is to the user's intent. 纯关键词匹配。
    """
    if not intent or not intent.get("keywords"):
        return (0.5, "未提供明确专业意向")

    name_norm = _normalize(major_name)
    keywords = intent["keywords"]

    norm_keywords = [(_normalize(kw), kw) for kw in keywords]
    exact_hits: List[str] = []
    overlap_hits: List[str] = []
    for kw_norm, kw in norm_keywords:
        if kw_norm and kw_norm in name_norm:
            exact_hits.append(kw)
        elif len(kw_norm) >= 2 and kw_norm in name_norm:
            overlap_hits.append(kw)

    exact_score = min(1.0, len(exact_hits) * 0.35)
    overlap_score = min(0.35, len(overlap_hits) * 0.12)
    total = min(1.0, exact_score + overlap_score)

    if exact_hits:
        reason = f"专业名称含意向关键词：{', '.join(exact_hits[:3])}"
    elif overlap_hits:
        reason = f"专业与意向领域相关：{', '.join(overlap_hits[:3])}"
    else:
        reason = "与考生意向关联度较低"

    return (round(total, 2), reason)
