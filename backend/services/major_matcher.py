"""
Major semantic matching for Spiral.

Problem: A candidate says "计算机 or 电子信息", but the database contains
计算机科学与技术, 软件工程, 人工智能, 网络空间安全, 物联网工程,
数据科学与大数据技术, 电子信息工程, 通信工程, 电子科学与技术,
微电子科学与工程, 集成电路设计与集成系统, 自动化, 电气工程及其自动化, etc.

We expand the user's free-text major preference into a structured intent vector
(keywords + categories), then score each major by relevance without calling LLM
per major.
"""

import json
import re
from typing import List, Dict, Optional, Tuple
from services.llm_service import chat_completion



_NORMALIZE_RE = re.compile(r"[\s\/\(\)（）]+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.lower())


def _expand_with_llm(preferred_major_text: str) -> Dict:
    """Use LLM to expand user major preference into keywords + broad categories."""
    system_prompt = (
        "你是高考志愿填报专家。请根据用户提到的意向专业，输出严格的 JSON 对象，不要任何解释。"
        "JSON 字段：\n"
        "- keywords: 相关具体专业名称列表（一级学科思维扩展，如电子信息可扩展到通信、微电子、集成电路、光电信息等），"
        "  考虑相近工科/理科/医科方向，不要过度扩展到无关领域\n"
        "- categories: 相关学科门类列表，从 [工科, 理科, 医科, 文科, 经管, 农科, 艺术, 法学, 教育] 中选择\n"
        "示例：{\"keywords\":[\"计算机科学与技术\",\"软件工程\",\"人工智能\",\"数据科学\",\"电子信息工程\"],\"categories\":[\"工科\",\"理科\"]}"
    )
    user_prompt = f"意向专业：{preferred_major_text}"
    try:
        raw = chat_completion(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2,
            max_tokens=512,
        )
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            # Backward compatibility: old list format
            return {"keywords": [str(x).strip() for x in parsed if str(x).strip()], "categories": []}
        return {
            "keywords": [str(x).strip() for x in parsed.get("keywords", []) if str(x).strip()],
            "categories": [str(x).strip() for x in parsed.get("categories", []) if str(x).strip()],
        }
    except Exception:
        return {"keywords": [], "categories": []}


def build_major_intent(preferred_major_text: Optional[str]) -> Dict:
    """
    Build a structured intent object from free-text major preference.
    完全由 LLM 一次性扩展为 keywords + categories；原始 tokens 仅作为补充命中。
    Returns: {
        "raw": original text,
        "keywords": [expanded keywords],
        "categories": [related broad categories],
    }
    """
    if not preferred_major_text:
        return {"raw": "", "keywords": [], "categories": []}

    raw = preferred_major_text

    # 1. LLM 扩展为核心
    llm_result = _expand_with_llm(raw)
    keywords: set = set(llm_result.get("keywords", []))
    categories: set = set(llm_result.get("categories", []))

    # 2. 保留原始 tokens 作为补充命中（不是 rule-based 扩展）
    for token in re.split(r"[、,，；;|/]", raw):
        token = token.strip()
        if token:
            keywords.add(token)

    return {
        "raw": raw,
        "keywords": sorted(keywords),
        "categories": sorted(categories),
    }


def score_major_relevance(major_name: str, major_category: Optional[str], intent: Dict) -> Tuple[float, str]:
    """
    Score how relevant a major is to the user's intent.
    Returns (score, reason).
    """
    if not intent or not intent.get("keywords"):
        return (0.5, "未提供明确专业意向")

    name_norm = _normalize(major_name)
    keywords = intent["keywords"]
    categories = intent["categories"]

    # Pre-normalize keywords once
    norm_keywords = [(_normalize(kw), kw) for kw in keywords]
    exact_hits: List[str] = []
    overlap_hits: List[str] = []
    for kw_norm, kw in norm_keywords:
        if kw_norm in name_norm:
            exact_hits.append(kw)
        elif len(kw_norm) >= 2 and kw_norm in name_norm:
            overlap_hits.append(kw)

    exact_score = min(1.0, len(exact_hits) * 0.35)

    # 2. Category match
    cat_score = 0.0
    if major_category:
        for cat in categories:
            if cat in major_category:
                cat_score = 0.25
                break

    overlap_score = min(0.35, len(overlap_hits) * 0.12)

    total = min(1.0, exact_score + cat_score + overlap_score)

    # Build reason
    if exact_hits:
        reason = f"专业名称含意向关键词：{', '.join(exact_hits[:3])}"
    elif overlap_hits:
        reason = f"专业与意向领域相关：{', '.join(overlap_hits[:3])}"
    elif cat_score > 0:
        reason = f"属于意向学科门类：{major_category}"
    else:
        reason = "与考生意向关联度较低"

    return (round(total, 2), reason)


def is_special_major(major_name: str) -> Tuple[bool, str]:
    """Detect special types that should be filtered out unless explicitly requested."""
    name = major_name.lower()
    if "预科" in name:
        return (True, "预科班")
    if "国家专项" in name or "专项计划" in name:
        return (True, "国家专项/专项计划")
    if "地方专项" in name:
        return (True, "地方专项")
    if "民族班" in name or "蒙授" in name or "藏班" in name:
        return (True, "民族班")
    if "定向" in name and ("西藏" in name or "新疆" in name or "基层" in name):
        return (True, "定向计划")
    return (False, "")


def is_science_engineering_related(major_name: str, major_category: Optional[str]) -> bool:
    """Heuristic for '理工科' preference."""
    name = major_name.lower()
    sci_eng_keywords = [
        "计算机", "软件", "人工智能", "电子信息", "通信", "电子", "微电子", "集成电路", "自动化",
        "电气", "机械", "车辆", "机器人", "智能制造", "测控", "仪器", "能源", "动力", "核工程",
        "航空航天", "兵器", "船舶", "海洋工程", "材料", "化学", "应用化学", "数学", "物理",
        "统计学", "数据科学", "大数据", "物联网", "信息安全", "网络安全", "光电", "生物医学工程",
        "土木", "建筑", "交通", "水利", "测绘", "地质", "矿业", "石油", "纺织", "轻工",
        "生物工程", "制药工程", "环境工程", "食品科学"
    ]
    if any(kw in name for kw in sci_eng_keywords):
        return True
    if major_category and "工科" in major_category:
        return True
    return False
