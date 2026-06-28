import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from agent.core import RecommendationAgent
from services.profile_parser import explain_parsing


router = APIRouter(prefix="/api", tags=["report"])

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def _build_report_data(text: str, rank: Optional[int], db: Session, province: Optional[str] = None):
    """Shared pipeline: parse -> recommend -> agent rationale."""
    agent = RecommendationAgent(text=text, rank=rank)
    state = agent.run(db)
    profile = state.profile
    result = {
        "profile": profile,
        "total_groups": state.groups_count,
        "冲_count": sum(1 for g in state.selected if g.level == "冲"),
        "稳_count": sum(1 for g in state.selected if g.level == "稳"),
        "保_count": sum(1 for g in state.selected if g.level == "保"),
        "recommendations": state.selected,
        "warnings": state.warnings,
    }
    explanations = explain_parsing(profile, text)
    return profile, result, explanations, state.trace


@router.post("/recommendations/from-text")
def recommend_from_text(payload: dict, db: Session = Depends(get_db)):
    """自由文本入口：返回 Agent 推荐结果与 trace。"""
    text = payload.get("text", "").strip()
    rank = payload.get("rank")
    province = payload.get("province", "").strip() or None
    if not text:
        raise HTTPException(status_code=400, detail="描述文本不能为空")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rank 必须是整数")

    try:
        profile, result, explanations, trace = _build_report_data(text, rank, db, province=province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "profile": profile,
        "total_groups": result["total_groups"],
        "冲_count": result["冲_count"],
        "稳_count": result["稳_count"],
        "保_count": result["保_count"],
        "recommendations": [g.model_dump() for g in result["recommendations"]],
        "warnings": result["warnings"],
        "trace": [t.__dict__ for t in trace],
    }


@router.post("/reports/from-text", response_class=HTMLResponse)
def report_from_text(request: Request, payload: dict, db: Session = Depends(get_db)):
    """直接返回一份完整的 HTML 志愿填报报告。"""
    text = payload.get("text", "").strip()
    rank = payload.get("rank")
    province = payload.get("province", "").strip() or None
    if not text:
        raise HTTPException(status_code=400, detail="描述文本不能为空")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rank 必须是整数")

    try:
        profile, result, explanations, trace = _build_report_data(text, rank, db, province=province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    template_result = {
        "total_groups": result["total_groups"],
        "冲_count": result["冲_count"],
        "稳_count": result["稳_count"],
        "保_count": result["保_count"],
        "warnings": result["warnings"],
        "recommendations": [g.model_dump() for g in result["recommendations"]],
    }

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "text": text,
            "profile": profile,
            "explanations": explanations,
            "result": template_result,
            "summary": "",
            "trace": [t.__dict__ for t in trace],
        },
    )
