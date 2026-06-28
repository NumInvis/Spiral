import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db, init_db
from config import list_provinces, get_province_rule
from models import Profile, School, Major, Document
from schemas import (
    ProfileCreate, ProfileOut,
    SchoolOut, SchoolDetailOut,
    RecommendationOut, SystemInfo,
    ProvinceRuleOut,
)
from recommendation import build_recommendation
from seed_data import seed
from routers import agent as agent_router
from routers import rag as rag_router
from routers import report as report_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = next(get_db())
    if db.query(School).first() is None:
        seed()
    yield


app = FastAPI(
    title="高考志愿填报 Agent API",
    description="基于 Agent + RAG 的高考志愿推荐系统后端",
    version="0.2.1",
    lifespan=lifespan,
)

# CORS：允许前端 1678 端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1678", "http://127.0.0.1:1678"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 子路由
app.include_router(agent_router.router)
app.include_router(rag_router.router)
app.include_router(report_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.2.1"}


@app.get("/api/system/info", response_model=SystemInfo)
def system_info():
    return SystemInfo(
        version="0.2.0",
        backend_port=11678,
        province_rules={p["province"]: get_province_rule(p["province"]) for p in list_provinces()},
    )


@app.get("/api/provinces")
def list_province_configs():
    return list_provinces()


@app.get("/api/province-rules/{province}", response_model=ProvinceRuleOut)
def get_rule(province: str):
    rule = get_province_rule(province)
    if not rule:
        raise HTTPException(status_code=404, detail="省份规则不存在")
    return rule


@app.post("/api/profiles", response_model=ProfileOut)
def create_profile(data: ProfileCreate, db: Session = Depends(get_db)):
    profile = Profile(**data.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/api/profiles", response_model=List[ProfileOut])
def list_profiles(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    return db.query(Profile).order_by(Profile.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/api/profiles/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.query(Profile).filter(Profile.id == profile_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found")
    return p


@app.post("/api/recommendations/{profile_id}", response_model=RecommendationOut)
def recommend(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    result = build_recommendation(profile, db)
    return result


@app.get("/api/schools", response_model=List[SchoolOut])
def list_schools(
    province: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(School)
    if province:
        q = q.filter(School.province == province)
    if level:
        q = q.filter(School.level == level)
    if city:
        q = q.filter(School.city == city)
    return q.all()


@app.get("/api/schools/{school_id}", response_model=SchoolDetailOut)
def get_school(school_id: int, db: Session = Depends(get_db)):
    s = db.query(School).filter(School.id == school_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="School not found")
    return s


@app.get("/api/schools/{school_id}/documents")
def get_school_documents(school_id: int, doc_type: Optional[str] = Query(None), db: Session = Depends(get_db)):
    s = db.query(School).filter(School.id == school_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="School not found")
    q = db.query(Document).filter(Document.school_name == s.name)
    if doc_type:
        q = q.filter(Document.doc_type == doc_type)
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "source_url": d.source_url} for d in q.all()]


@app.get("/api/majors/search")
def search_majors(
    q: Optional[str] = Query(None, description="专业名称关键词"),
    category: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Major).join(School, Major.school_id == School.id)
    if q:
        query = query.filter(Major.name.contains(q))
    if category:
        query = query.filter(Major.category == category)
    if province:
        query = query.filter(School.province == province)
    majors = query.limit(50).all()
    return [{
        "id": m.id,
        "name": m.name,
        "school": m.school.name,
        "group_code": m.group_code,
        "category": m.category,
        "subject_require": m.subject_require,
        "province": m.school.province,
    } for m in majors]


@app.post("/api/admin/import-data")
def admin_import_data(
    province: str = Query("湖北", description="数据所属省份"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """管理员入口：上传官方 CSV/Excel 投档线数据并导入。"""
    from services.data_importer import import_hubei_csv
    import tempfile
    suffix = os.path.splitext(file.filename)[1] or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    try:
        stats = import_hubei_csv(db, csv_path=tmp_path, clear=False)
        return {"ok": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 11678))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
