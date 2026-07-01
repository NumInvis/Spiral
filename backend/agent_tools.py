"""
Spiral ReAct Agent — tool definitions and executors.

Each tool has:
  - name: str
  - description: str (for LLM to understand what it does)
  - parameters: JSON Schema (for LLM to construct valid calls)
  - execute: callable(**kwargs) -> dict (actual implementation)

The agent loop sends tool definitions to the LLM as OpenAI-format tools.
When the LLM calls a tool, we execute it and feed the result back.
"""

from __future__ import annotations
import json
import re
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from sqlalchemy import and_
from sqlalchemy.orm import Session, selectinload

from models import School, Major, MajorScore, RankTable
from config.province_rules import LATEST_HISTORICAL_YEAR
from services.llm_service import chat_completion
from services.major_matcher import build_major_intent, score_major_relevance


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str = ""


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    execute: Callable[..., ToolResult]


_TOOLS: Dict[str, ToolDef] = {}


def _filter_params(fn: Callable, kwargs: dict) -> dict:
    """Only pass parameters that fn actually accepts."""
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if has_var_keyword:
            return kwargs
        accepted = set(params.keys())
        return {k: v for k, v in kwargs.items() if k in accepted}
    except (ValueError, TypeError):
        return kwargs


def register_tool(name: str, description: str, parameters: dict):
    """Decorator to register a tool."""
    def decorator(fn: Callable[..., ToolDef]):
        def wrapper(**kwargs) -> ToolResult:
            try:
                filtered = _filter_params(fn, kwargs)
                result = fn(**filtered)
                if isinstance(result, ToolResult):
                    return result
                return ToolResult(ok=True, data=result)
            except Exception as e:
                return ToolResult(ok=False, error=str(e))
        _TOOLS[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            execute=wrapper,
        )
        return wrapper
    return decorator


def get_tool(name: str) -> Optional[ToolDef]:
    return _TOOLS.get(name)


def all_tools() -> List[ToolDef]:
    return list(_TOOLS.values())


def tools_for_openai() -> List[dict]:
    """Convert to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
        }
        for t in _TOOLS.values()
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@register_tool(
    name="query_score_lines",
    description="查询指定省份、科类、年份的院校专业组投档线数据。返回专业组代码、院校名称、投档位次、分数、数据置信度。可额外按专业名称关键词过滤。",
    parameters={
        "type": "object",
        "properties": {
            "province": {"type": "string", "description": "省份，如 湖北"},
            "subject_type": {"type": "string", "description": "科类：物理 或 历史"},
            "year": {"type": "integer", "description": "年份，如 2025"},
            "major_keyword": {"type": "string", "description": "专业名称关键词过滤（可选）"},
            "limit": {"type": "integer", "description": "返回条数上限，默认 200"},
        },
        "required": ["province", "subject_type", "year"],
    },
)
def _query_score_lines(
    db: Session,
    province: str,
    subject_type: str,
    year: int = LATEST_HISTORICAL_YEAR,
    major_keyword: str = "",
    limit: int = 200,
) -> ToolResult:
    q = (
        db.query(MajorScore)
        .join(Major)
        .join(School)
        .filter(
            MajorScore.province == province,
            MajorScore.subject_type == subject_type,
            MajorScore.year == year,
            MajorScore.group_lowest_rank.isnot(None),
        )
        .options(selectinload(MajorScore.major).selectinload(Major.school))
    )
    if major_keyword:
        q = q.filter(Major.name.contains(major_keyword))
    rows = q.limit(limit).all()
    results = []
    for ms in rows:
        results.append({
            "school_name": ms.major.school.name,
            "school_level": ms.major.school.level,
            "school_city": ms.major.school.city,
            "major_name": ms.major.name,
            "group_code": ms.group_code or ms.major.group_code or "01",
            "group_lowest_rank": ms.group_lowest_rank,
            "group_lowest_score": ms.group_lowest_score,
            "data_confidence": ms.data_confidence,
        })
    return ToolResult(ok=True, data=results)


@register_tool(
    name="query_rank_table",
    description="查询指定省份、科类、年份的一分一段表。返回分数-位次对应关系，用于等位分换算。",
    parameters={
        "type": "object",
        "properties": {
            "province": {"type": "string", "description": "省份"},
            "subject_type": {"type": "string", "description": "科类：物理 或 历史"},
            "year": {"type": "integer", "description": "年份"},
        },
        "required": ["province", "subject_type", "year"],
    },
)
def _query_rank_table(
    db: Session,
    province: str,
    subject_type: str,
    year: int,
) -> ToolResult:
    rows = (
        db.query(RankTable)
        .filter(
            RankTable.province == province,
            RankTable.subject_type == subject_type,
            RankTable.year == year,
            RankTable.accumulate.isnot(None),
        )
        .order_by(RankTable.score.desc())
        .all()
    )
    if not rows:
        return ToolResult(ok=False, error=f"缺少 {year} 年 {province} {subject_type} 一分一段表")
    data = [{"score": r.score, "num": r.num, "accumulate": r.accumulate} for r in rows]
    return ToolResult(ok=True, data=data)


@register_tool(
    name="estimate_probability",
    description="根据考生位次和专业组投档位次估算录取概率。返回 0-1 之间的概率值。",
    parameters={
        "type": "object",
        "properties": {
            "candidate_rank": {"type": "integer", "description": "考生位次"},
            "ref_rank": {"type": "integer", "description": "参考位次（专业组投档位次）"},
        },
        "required": ["candidate_rank", "ref_rank"],
    },
)
def _estimate_probability(
    candidate_rank: int,
    ref_rank: int,
) -> ToolResult:
    if ref_rank <= 0:
        return ToolResult(ok=True, data={"probability": 0.5})
    rank_ratio = candidate_rank / ref_rank
    prob = 1.0 / (1.0 + max(0, rank_ratio - 0.85) * 4.0)
    prob = max(0.02, min(0.99, prob))
    return ToolResult(ok=True, data={"probability": round(prob, 4)})


@register_tool(
    name="expand_major_intent",
    description="使用 LLM 将用户的意向专业文本扩展为关键词列表和学科门类。例如'计算机'扩展为[计算机科学与技术, 软件工程, 人工智能, ...]和[工科, 理科]。",
    parameters={
        "type": "object",
        "properties": {
            "preferred_major_text": {"type": "string", "description": "用户原始意向专业描述"},
        },
        "required": ["preferred_major_text"],
    },
)
def _expand_major_intent(preferred_major_text: str) -> ToolResult:
    intent = build_major_intent(preferred_major_text)
    return ToolResult(ok=True, data=intent)


@register_tool(
    name="score_major_relevance",
    description="评估单个专业名称与考生意向专业的相关度，返回 0-1 分数和理由。",
    parameters={
        "type": "object",
        "properties": {
            "major_name": {"type": "string", "description": "待评估的专业名称"},
            "intent": {"type": "object", "description": "由 expand_major_intent 返回的意图对象"},
        },
        "required": ["major_name", "intent"],
    },
)
def _score_major_relevance(major_name: str, intent: dict) -> ToolResult:
    score, reason = score_major_relevance(major_name, None, intent)
    return ToolResult(ok=True, data={"score": score, "reason": reason})


@register_tool(
    name="filter_special_types",
    description="过滤特殊类型招生（国家专项、预科、定向、民族班等）。输入专业名称列表，返回过滤后的列表和被过滤掉的条目。",
    parameters={
        "type": "object",
        "properties": {
            "major_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "专业名称列表",
            },
            "allow_special": {
                "type": "boolean",
                "description": "是否允许特殊类型（默认 false）",
            },
        },
        "required": ["major_names"],
    },
)
def _filter_special_types(
    major_names: List[str],
    allow_special: bool = False,
) -> ToolResult:
    if allow_special:
        return ToolResult(ok=True, data={"kept": major_names, "removed": []})
    special_keywords = [
        "国家专项", "地方专项", "高校专项", "预科", "民族班",
        "定向", "援藏", "南疆", "边防军人子女", "中外合作",
        "护理类", "高收费", "公费师范", "国际班", "马来西亚分校",
    ]
    kept, removed = [], []
    for name in major_names:
        if any(kw in name for kw in special_keywords):
            removed.append(name)
        else:
            kept.append(name)
    return ToolResult(ok=True, data={"kept": kept, "removed": removed})


@register_tool(
    name="get_equivalent_rank",
    description="等位分换算：将某年份的位次换算为另一年的等效位次。需要两年的一分一段表都存在。",
    parameters={
        "type": "object",
        "properties": {
            "rank": {"type": "integer", "description": "原始位次"},
            "from_year": {"type": "integer", "description": "原始年份"},
            "to_year": {"type": "integer", "description": "目标年份"},
            "province": {"type": "string", "description": "省份"},
            "subject_type": {"type": "string", "description": "科类"},
        },
        "required": ["rank", "from_year", "to_year", "province", "subject_type"],
    },
)
def _get_equivalent_rank(
    db: Session,
    rank: int,
    from_year: int,
    to_year: int,
    province: str,
    subject_type: str,
) -> ToolResult:
    from recommendation import rank_to_equivalent
    try:
        result = rank_to_equivalent(rank, from_year, to_year, province, subject_type, db)
        return ToolResult(ok=True, data={"equivalent_rank": result})
    except ValueError as e:
        return ToolResult(ok=False, error=str(e))


@register_tool(
    name="get_school_detail",
    description="获取指定院校的详细信息（层次、城市、学科评估、硕博点等）。",
    parameters={
        "type": "object",
        "properties": {
            "school_name": {"type": "string", "description": "院校名称"},
        },
        "required": ["school_name"],
    },
)
def _get_school_detail(db: Session, school_name: str) -> ToolResult:
    school = db.query(School).filter(School.name == school_name).first()
    if not school:
        return ToolResult(ok=False, error=f"院校不存在: {school_name}")
    return ToolResult(ok=True, data={
        "name": school.name,
        "code": school.code,
        "level": school.level,
        "province": school.province,
        "city": school.city,
        "category": school.category,
        "has_master": school.has_master,
        "has_phd": school.has_phd,
        "tags": school.tags,
    })
