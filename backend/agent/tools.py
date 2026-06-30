"""Tools for the RecommendationAgent.

Each tool receives the current AgentState and a DB session, mutates/extends the
state, and returns it.  The orchestrator in core.py calls them in order and
records every step in the trace.
"""

import os
import traceback
from typing import Any, Dict

from sqlalchemy.orm import Session

from agent.state import AgentState, AgentStep
from services.profile_parser import parse_free_text
from recommendation import build_recommendation
from models import Profile


def _add_step(state: AgentState, name: str, status: str = "running", input_summary: str = "", output_summary: str = "", details: Dict[str, Any] = None) -> AgentStep:
    step = AgentStep(
        step=len(state.trace) + 1,
        name=name,
        status=status,
        input_summary=input_summary,
        output_summary=output_summary,
        details=details or {},
    )
    state.trace.append(step)
    return step


def _require_llm() -> None:
    if not os.environ.get("WINCODE_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("LLM API key 未配置：必须设置 WINCODE_API_KEY 或 OPENAI_API_KEY 才能使用 Agent")


def parse_profile_tool(state: AgentState, db: Session) -> AgentState:
    """Parse free-text requirements into a structured Profile via LLM."""
    _require_llm()
    step = _add_step(
        state,
        "解析画像",
        input_summary=f"文本：{state.original_text[:120]}..." if len(state.original_text) > 120 else f"文本：{state.original_text}",
    )
    try:
        profile_create = parse_free_text(state.original_text, rank=state.rank)
        profile = Profile(
            name=profile_create.name or "考生",
            province=profile_create.province,
            subject_type=profile_create.subject_type,
            score=profile_create.score or 0,
            rank=profile_create.rank,
            preferred_major=profile_create.preferred_major,
            preferred_city=profile_create.preferred_city,
            strategy=profile_create.strategy,
            risk_preference=profile_create.risk_preference,
            accept_adjustment=profile_create.accept_adjustment,
            allow_special_types=profile_create.allow_special_types,
        )
        db.add(profile)
        db.flush()
        db.refresh(profile)
        state.profile = profile
        step.status = "done"
        step.output_summary = (
            f"省份={profile.province} 科类={profile.subject_type} 位次={profile.rank} "
            f"意向={profile.preferred_major or '无'} 城市={profile.preferred_city or '无'} "
            f"风险偏好={profile.risk_preference}"
        )
        step.details = {
            "province": profile.province,
            "subject_type": profile.subject_type,
            "rank": profile.rank,
            "preferred_major": profile.preferred_major,
            "preferred_city": profile.preferred_city,
            "risk_preference": profile.risk_preference,
        }
    except Exception as e:
        step.status = "error"
        step.output_summary = f"画像解析失败：{e}"
        step.details = {"error": str(e), "traceback": traceback.format_exc()}
        raise
    return state


def retrieve_candidates_tool(state: AgentState, db: Session) -> AgentState:
    """Run the validated recommendation engine to retrieve candidate pool."""
    if state.profile is None:
        raise RuntimeError("Profile not parsed")
    step = _add_step(
        state,
        "检索候选池",
        input_summary=f"位次={state.profile.rank} 科类={state.profile.subject_type} 风险偏好={state.profile.risk_preference}",
    )
    try:
        result = build_recommendation(state.profile, db)
        state.selected = result.get("recommendations", [])
        state.special_selected = result.get("special_recommendations", [])
        state.groups_count = len(state.selected)
        state.warnings = result.get("warnings", [])
        conf_dist: Dict[str, int] = {}
        for g in state.selected:
            conf_dist[g.data_confidence] = conf_dist.get(g.data_confidence, 0) + 1
        step.status = "done"
        special_count = len(state.special_selected)
        step.output_summary = (
            f"候选池共 {state.groups_count} 个专业组（冲={result.get('冲_count')} "
            f"稳={result.get('稳_count')} 保={result.get('保_count')}）；"
            f"特殊类型 {special_count} 个；置信分布 {conf_dist}"
        )
        step.details = {
            "total_groups": state.groups_count,
            "冲_count": result.get("冲_count"),
            "稳_count": result.get("稳_count"),
            "保_count": result.get("保_count"),
            "special_count": special_count,
            "confidence_distribution": conf_dist,
        }
    except Exception as e:
        step.status = "error"
        step.output_summary = f"候选检索失败：{e}"
        step.details = {"error": str(e), "traceback": traceback.format_exc()}
        raise
    return state


def risk_check_tool(state: AgentState, db: Session) -> AgentState:
    """Agent-level review of the candidate pool.  Keep warnings factual and minimal."""
    step = _add_step(
        state,
        "风险复核",
        input_summary=f"候选池 {len(state.selected)} 组",
    )
    # 不再生成主观风险提示；仅记录数据置信度分布
    conf_dist: Dict[str, int] = {}
    for g in state.selected:
        conf_dist[g.data_confidence] = conf_dist.get(g.data_confidence, 0) + 1
    step.status = "done"
    step.output_summary = f"候选池数据置信分布 {conf_dist}"
    step.details = {"confidence_distribution": conf_dist}
    return state
