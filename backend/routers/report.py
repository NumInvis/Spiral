import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import Profile
from schemas import RecommendationOut
from recommendation import build_recommendation
from services.profile_parser import parse_free_text, explain_parsing
from services.llm_service import generate_report_summary


router = APIRouter(prefix="/api", tags=["report"])

# Jinja2 templates directory (relative to this file: ../templates)
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
os.makedirs(TEMPLATE_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def _build_report_data(text: str, rank: Optional[int], db: Session, with_summary: bool = True, province: Optional[str] = None):
    """Shared pipeline: parse -> recommend -> explain -> optional LLM summary."""
    profile_data = parse_free_text(text, rank, province=province)
    profile = Profile(**profile_data.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)

    result = build_recommendation(profile, db)
    explanations = explain_parsing(profile_data, text)

    summary = ""
    if with_summary:
        # Try to get a personalized LLM summary; fall back gracefully
        try:
            summary = generate_report_summary(profile_data.model_dump(), result)
        except Exception:
            summary = ""

    return profile, profile_data, result, explanations, summary


@router.post("/recommendations/from-text", response_model=RecommendationOut)
def recommend_from_text(payload: dict, db: Session = Depends(get_db)):
    """
    自由文本入口：用户用自然语言描述志愿意向，并提供省排名。
    系统自动解析为结构化画像，生成推荐方案。
    """
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
        profile, profile_data, result, explanations, summary = _build_report_data(text, rank, db, with_summary=False, province=province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/reports/from-text", response_class=HTMLResponse)
def report_from_text(request: Request, payload: dict, db: Session = Depends(get_db)):
    """
    直接返回一份完整的 HTML 志愿填报报告。
    """
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
        profile, profile_data, result, explanations, summary = _build_report_data(text, rank, db, province=province)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 为 HTML 模板提供可 JSON 序列化的 plain dict
    template_result = {
        "total_groups": result["total_groups"],
        "冲_count": result["冲_count"],
        "稳_count": result["稳_count"],
        "保_count": result["保_count"],
        "warnings": result["warnings"],
        "recommendations": [r.model_dump() for r in result["recommendations"]],
    }

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "text": text,
            "profile": profile,
            "explanations": explanations,
            "result": template_result,
            "summary": summary,
        },
    )
