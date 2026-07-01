import os
import asyncio
import concurrent.futures
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import SessionLocal
from agent_loop import run_agent, AgentState


_report_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="report")


class ReportPayload(BaseModel):
    text: str
    rank: Optional[int] = None
    province: Optional[str] = None
    subject_type: Optional[str] = None


router = APIRouter(prefix="/api", tags=["report"])

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def _build_explanations(state: AgentState) -> List[Dict]:
    """Build human-readable explanations from agent trace."""
    explanations = []
    if state.profile:
        p = state.profile
        if p.get("province"):
            explanations.append({"item": "省份", "value": p["province"], "reason": "前端传入"})
        if p.get("subject_type"):
            explanations.append({"item": "科类", "value": p["subject_type"], "reason": "前端传入"})
        if p.get("rank"):
            explanations.append({"item": "位次", "value": str(p["rank"]), "reason": "前端传入"})
        if p.get("preferred_major"):
            explanations.append({"item": "意向专业", "value": p["preferred_major"], "reason": "从描述提取"})
        if p.get("excluded_majors"):
            explanations.append({"item": "排除专业", "value": p["excluded_majors"], "reason": "从描述提取"})
        if p.get("risk_preference"):
            explanations.append({"item": "风险偏好", "value": p["risk_preference"], "reason": "从描述提取"})
    explanations.append({"item": "推荐组数", "value": str(len(state.selected)), "reason": f"Agent 经过 {len(state.trace)} 轮推理生成"})
    return explanations


def _add_trace_step(state, name, status, summary):
    """向 state.trace 追加一步。"""
    from agent_loop import AgentStep
    step = AgentStep(
        step=len(state.trace) + 1,
        name=name,
        status=status,
        output_summary=summary,
    )
    state.trace.append(step)
    return step


def _run_agent_sync(text: str, rank: Optional[int], province: Optional[str], subject_type: Optional[str]) -> AgentState:
    """Run agent in a thread with its own DB session."""
    db = SessionLocal()
    try:
        return run_agent(text=text, db=db, rank=rank, province=province, subject_type=subject_type)
    finally:
        db.close()


@router.post("/reports/from-text", response_class=HTMLResponse)
async def report_from_text(request: Request, payload: ReportPayload):
    """直接返回一份完整的 HTML 志愿填报报告。"""
    text = payload.text.strip()
    rank = payload.rank
    province = (payload.province or "").strip() or None
    subject_type = (payload.subject_type or "").strip() or None
    if not text:
        raise HTTPException(status_code=400, detail="描述文本不能为空")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rank 必须是整数")

    loop = asyncio.get_event_loop()
    try:
        state = await loop.run_in_executor(_report_executor, _run_agent_sync, text, rank, province, subject_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    explanations = _build_explanations(state)

    # 构造轮1候选池快照（供轮2替换取用）
    candidate_pool_snapshot = [
        {
            "level": getattr(r, "level", r.get("level") if isinstance(r, dict) else ""),
            "school_name": getattr(r, "school_name", r.get("school_name") if isinstance(r, dict) else ""),
            "school_level": getattr(r, "school_level", r.get("school_level") if isinstance(r, dict) else ""),
            "group_code": getattr(r, "group_code", r.get("group_code") if isinstance(r, dict) else ""),
            "ref_rank": (getattr(r, "year_breakdown", None) or ([{}] if not isinstance(r, dict) else r.get("year_breakdown", [{}]))),
        }
        for r in (state.selected or [])
    ]

    # 轮2: LLM 独立质检（轻微自改交付，严重带意见回退轮1）
    summary = ""
    try:
        from services.llm_service import review_and_summarize
        review = review_and_summarize(
            state.profile or {}, state.selected, state.original_text,
            candidate_pool=candidate_pool_snapshot,
        )
        severity = review.get("severity", "ok")

        if severity == "major":
            # 严重不符：带着轮2意见回退轮1重跑（仅一次，避免死循环）
            issues = review.get("issues", [])
            retry_step = _add_trace_step(state, "轮1重跑（轮2反馈）", "running",
                                          f"轮2反馈: {issues}")
            from agent_loop import _llm_final_reasoning, _post_process
            # 把轮2意见塞进轮1上下文重跑
            state._review_feedback = issues
            final = _llm_final_reasoning(state, [], state.profile or {})
            if final:
                state.final_result = final
                state.selected = final.get("recommendations", [])
                state.warnings = final.get("warnings", [])
                retry_db = SessionLocal()
                try:
                    _post_process(state, retry_db)
                finally:
                    retry_db.close()
                retry_step.status = "done"
                retry_step.output_summary = f"轮1重跑输出 {len(state.selected)} 条"
            else:
                retry_step.status = "error"
                retry_step.output_summary = "轮1重跑失败，沿用原方案"
        elif severity == "minor":
            # 轻微：轮2已自行微调，直接采用
            revised = review.get("recommendations")
            if revised:
                state.selected = revised
            review_step = _add_trace_step(state, "轮2微调", "done",
                                          f"轮2自行调整 {len(state.selected)} 条")
        summary = review.get("summary", "")
        if review.get("issues"):
            state.warnings.extend(review["issues"])
    except Exception as e:
        summary = f"[复审生成失败：{e}]"

    template_result = {
        "total_groups": len(state.selected),
        "冲_count": sum(1 for g in state.selected if g.get("level") == "冲"),
        "稳_count": sum(1 for g in state.selected if g.get("level") == "稳"),
        "保_count": sum(1 for g in state.selected if g.get("level") == "保"),
        "warnings": state.warnings,
        "recommendations": state.selected,
        "special_recommendations": [],
        "special_by_type": {},
    }

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "text": text,
            "profile": state.profile or {},
            "explanations": explanations,
            "result": template_result,
            "summary": summary,
            "trace": [t.__dict__ for t in state.trace],
        },
    )
