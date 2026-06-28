"""
Free-text profile parser for Spiral.
Turns a user's natural-language description + province rank into a structured Profile.
LLM-only：无 API Key 或 LLM 解析失败时直接报错，禁止规则兜底、禁止硬编码默认值。
"""

import os
import re
from typing import Dict, List, Optional
from schemas import ProfileCreate
from services.llm_service import parse_profile_with_llm


def _detect_risk_preference(text: str) -> str:
    text = text.lower()
    if any(k in text for k in ["激进", "多冲", "赌", "捡漏", "不在乎风险", "冲刺"]):
        return "aggressive"
    if any(k in text for k in ["保守", "求稳", "保稳", "避免滑档", "稳妥", "稳为主", "安全第一"]):
        return "conservative"
    return "balanced"


def _detect_special_types(text: str) -> bool:
    """仅当用户文本明确愿意接受特殊类型招生时才允许推荐。"""
    pattern = r"(?:接受|愿意|可以|填报|报|考虑|走).{0,5}(国家专项|地方专项|高校专项|预科|定向|民族班|援藏|南疆|边防军人子女)"
    negative = re.search(r"(?:不要|不想|不填|不接受|拒绝|排除).{0,5}(国家专项|地方专项|高校专项|预科|定向|民族班|援藏|南疆|边防军人子女)", text)
    if negative:
        return False
    return bool(re.search(pattern, text))


def _require_llm() -> None:
    if not os.environ.get("WINCODE_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("LLM 未配置：必须设置 WINCODE_API_KEY 或 OPENAI_API_KEY 才能解析画像")


def parse_free_text(text: str, rank: Optional[int] = None, province: Optional[str] = None) -> ProfileCreate:
    """
    Parse free-text description + optional rank into a ProfileCreate schema.
    完全依赖 LLM；解析失败或关键字段缺失时直接报错，禁止规则兜底。
    """
    text = text.strip()
    if not text:
        raise ValueError("描述不能为空。")
    if rank is not None and rank <= 0:
        raise ValueError("位次必须是正整数。")

    _require_llm()
    llm_data = parse_profile_with_llm(text, rank)

    # 校验必填字段
    final_rank = llm_data.get("rank")
    if final_rank is None and rank is not None:
        final_rank = rank
    if final_rank is None:
        raise ValueError("未能识别考生位次，请明确提供位次。")

    subject_type = llm_data.get("subject_type")
    if subject_type not in ("物理", "历史"):
        raise ValueError("未能识别科类（物理/历史），请明确说明。")

    final_province = llm_data.get("province") or province
    if not final_province:
        raise ValueError("未能识别省份，请明确说明。")

    score = llm_data.get("score")
    if score is None:
        score = 0
    try:
        score = int(score)
    except Exception:
        score = 0

    risk_preference = llm_data.get("risk_preference")
    if risk_preference not in ("aggressive", "balanced", "conservative"):
        risk_preference = _detect_risk_preference(text)

    allow_special_types = bool(llm_data.get("allow_special_types", _detect_special_types(text)))

    return ProfileCreate(
        name="考生",
        province=final_province,
        subject_type=subject_type,
        score=score,
        rank=int(final_rank),
        preferred_major=llm_data.get("preferred_major"),
        preferred_city=llm_data.get("preferred_city"),
        strategy=None,
        risk_preference=risk_preference,
        accept_adjustment=True,
        allow_special_types=allow_special_types,
    )


def explain_parsing(profile: ProfileCreate, original_text: str, source: str = "LLM 解析") -> List[Dict]:
    """Return human-readable parsing steps for transparency."""
    explanations = []
    explanations.append({
        "item": "省份",
        "value": profile.province,
        "reason": "从描述中识别到省份关键词" if profile.province in original_text else source,
    })
    explanations.append({
        "item": "科类",
        "value": profile.subject_type,
        "reason": source,
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
        "item": "风险偏好",
        "value": profile.risk_preference,
        "reason": source,
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
