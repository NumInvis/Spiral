from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import School, Major, MajorScore
from services import SearchAgent
from config.province_rules import LATEST_HISTORICAL_YEAR

router = APIRouter(prefix="/api/agent", tags=["agent"])


class FillDataRequest(BaseModel):
    school_name: str
    major_name: str
    province: str
    subject_type: str
    year: int = LATEST_HISTORICAL_YEAR
    write_to_db: bool = False


class BulkFillRequest(BaseModel):
    province: str
    subject_type: str
    year: int = LATEST_HISTORICAL_YEAR
    limit: int = 10
    write_to_db: bool = True


def _get_agent():
    return SearchAgent()


@router.post("/fill-data")
def fill_data(req: FillDataRequest, agent: SearchAgent = Depends(_get_agent)):
    result = agent.fill_major_score(
        req.school_name, req.major_name, req.province, req.subject_type, req.year
    )
    return result


@router.post("/fill-data-and-write")
def fill_data_and_write(req: FillDataRequest, db: Session = Depends(get_db), agent: SearchAgent = Depends(_get_agent)):
    result = agent.fill_major_score(
        req.school_name, req.major_name, req.province, req.subject_type, req.year
    )
    best = result.get("best_guess") or {}
    if not best.get("score") and not best.get("rank"):
        raise HTTPException(status_code=404, detail="未检索到有效数据")

    school = db.query(School).filter(School.name == req.school_name).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    major = (
        db.query(Major)
        .filter(Major.school_id == school.id, Major.name.contains(req.major_name))
        .first()
    )
    if not major:
        # 若专业不存在则自动创建一个占位专业
        major = Major(
            school_id=school.id,
            name=req.major_name,
            category=None,
            subject_require="不限",
        )
        db.add(major)
        db.flush()

    existing = (
        db.query(MajorScore)
        .filter(
            MajorScore.major_id == major.id,
            MajorScore.province == req.province,
            MajorScore.subject_type == req.subject_type,
            MajorScore.year == req.year,
        )
        .first()
    )
    if existing:
        existing.lowest_score = best.get("score")
        existing.lowest_rank = best.get("rank")
        existing.data_confidence = best.get("confidence", "C")
        existing.data_source = "Web Search Agent 补录"
    else:
        db.add(
            MajorScore(
                major_id=major.id,
                province=req.province,
                subject_type=req.subject_type,
                year=req.year,
                lowest_score=best.get("score"),
                lowest_rank=best.get("rank"),
                data_confidence=best.get("confidence", "C"),
                data_source="Web Search Agent 补录",
            )
        )
    db.commit()
    return {**result, "written": True, "major_id": major.id}


@router.post("/bulk-fill")
def bulk_fill(req: BulkFillRequest, db: Session = Depends(get_db), agent: SearchAgent = Depends(_get_agent)):
    """批量补录缺失位次的专业（优先 985/211 以下院校）。"""
    # 找出该省份科类下没有最新历史年份位次数据的专业
    subq = (
        db.query(MajorScore.major_id)
        .filter(
            MajorScore.province == req.province,
            MajorScore.subject_type == req.subject_type,
            MajorScore.year == req.year,
            MajorScore.lowest_rank.isnot(None),
        )
        .subquery()
    )
    majors = (
        db.query(Major, School)
        .join(School, Major.school_id == School.id)
        .filter(~Major.id.in_(subq))
        .limit(req.limit)
        .all()
    )
    results = []
    for major, school in majors:
        res = agent.fill_major_score(
            school.name, major.name, req.province, req.subject_type, req.year
        )
        best = res.get("best_guess") or {}
        if req.write_to_db and (best.get("score") or best.get("rank")):
            db.add(
                MajorScore(
                    major_id=major.id,
                    province=req.province,
                    subject_type=req.subject_type,
                    year=req.year,
                    lowest_score=best.get("score"),
                    lowest_rank=best.get("rank"),
                    data_confidence=best.get("confidence", "C"),
                    data_source="Web Search Agent 补录",
                )
            )
        results.append({
            "school": school.name,
            "major": major.name,
            "best_guess": best,
        })
    if req.write_to_db:
        db.commit()
    return {"filled": len(results), "results": results}
