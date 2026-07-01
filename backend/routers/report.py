import os
import asyncio
import concurrent.futures
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from agent_loop import run_agent, AgentState


_report_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="report")


class ReportPayload(BaseModel):
    text: str
    rank: Optional[int] = None
    province: Optional[str] = None


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
            explanations.append({"item": "省份", "value": p["province"], "reason": "从描述中识别"})
        if p.get("subject_type"):
            explanations.append({"item": "科类", "value": p["subject_type"], "reason": "从描述中识别"})
        if p.get("rank"):
            explanations.append({"item": "位次", "value": str(p["rank"]), "reason": "用户提供或从文本提取"})
        if p.get("preferred_major"):
            explanations.append({"item": "意向专业", "value": p["preferred_major"], "reason": "LLM 解析"})
        if p.get("risk_preference"):
            explanations.append({"item": "风险偏好", "value": p["risk_preference"], "reason": "LLM 判断"})
    explanations.append({"item": "推荐组数", "value": str(len(state.selected)), "reason": f"Agent 经过 {len(state.trace)} 轮推理生成"})
    return explanations


def _run_agent_sync(text: str, rank: Optional[int], province: Optional[str]) -> AgentState:
    """Run agent in a thread with its own DB session."""
    db = SessionLocal()
    try:
        return run_agent(text=text, db=db, rank=rank, province=province)
    finally:
        db.close()


@router.post("/recommendations/from-text")
async def recommend_from_text(payload: ReportPayload):
    """自由文本入口：ReAct Agent 推荐结果与 trace。"""
    text = payload.text.strip()
    rank = payload.rank
    province = (payload.province or "").strip() or None
    if not text:
        raise HTTPException(status_code=400, detail="描述文本不能为空")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rank 必须是整数")

    loop = asyncio.get_event_loop()
    try:
        state = await loop.run_in_executor(_report_executor, _run_agent_sync, text, rank, province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "profile": state.profile,
        "total_groups": len(state.selected),
        "冲_count": sum(1 for g in state.selected if g.get("level") == "冲"),
        "稳_count": sum(1 for g in state.selected if g.get("level") == "稳"),
        "保_count": sum(1 for g in state.selected if g.get("level") == "保"),
        "recommendations": state.selected,
        "warnings": state.warnings,
        "trace": [t.__dict__ for t in state.trace],
        "iterations": len(state.trace),
    }


@router.post("/reports/from-text", response_class=HTMLResponse)
async def report_from_text(request: Request, payload: ReportPayload):
    """直接返回一份完整的 HTML 志愿填报报告。"""
    text = payload.text.strip()
    rank = payload.rank
    province = (payload.province or "").strip() or None
    if not text:
        raise HTTPException(status_code=400, detail="描述文本不能为空")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rank 必须是整数")

    loop = asyncio.get_event_loop()
    try:
        state = await loop.run_in_executor(_report_executor, _run_agent_sync, text, rank, province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    explanations = _build_explanations(state)
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
            "summary": "",
            "trace": [t.__dict__ for t in state.trace],
        },
    )
