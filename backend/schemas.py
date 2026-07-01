from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ProfileCreate(BaseModel):
    name: Optional[str] = None
    province: str = Field(..., min_length=1)
    subject_type: str = Field(..., pattern="^(物理|历史)$")
    score: int = Field(..., ge=0, le=750)
    rank: int = Field(..., ge=1)
    preferred_major: Optional[str] = None
    preferred_city: Optional[str] = None
    excluded_majors: Optional[str] = None
    risk_preference: str = Field(default="balanced", pattern="^(aggressive|balanced|conservative)$")
    allow_special_types: bool = False


class ProfileOut(ProfileCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SchoolOut(BaseModel):
    id: int
    code: str
    name: str
    level: Optional[str]
    province: Optional[str]
    city: Optional[str]
    is_public: bool
    has_master: bool
    has_phd: bool

    class Config:
        from_attributes = True


class MajorScoreOut(BaseModel):
    year: int
    province: str
    subject_type: str
    lowest_score: Optional[int]
    avg_score: Optional[int]
    highest_score: Optional[int]
    lowest_rank: Optional[int]
    data_confidence: str

    class Config:
        from_attributes = True


class AdmissionPlanOut(BaseModel):
    year: int
    province: str
    subject_type: str
    plan_count: int
    group_code: Optional[str]

    class Config:
        from_attributes = True


class MajorOut(BaseModel):
    id: int
    code: Optional[str]
    name: str
    category: Optional[str]
    subject_require: Optional[str]
    duration: int
    tuition: Optional[int]
    discipline_eval: Optional[str]
    employment_score: float
    scores: List[MajorScoreOut] = []
    plans: List[AdmissionPlanOut] = []

    class Config:
        from_attributes = True


class SchoolDetailOut(SchoolOut):
    majors: List[MajorOut] = []


class RecommendationItem(BaseModel):
    group_index: int
    level: str  # 冲 / 稳 / 保
    school_id: int
    school_code: str
    school_name: str
    school_level: Optional[str]
    city: Optional[str]
    group_code: Optional[str]
    majors: List[dict]
    year_breakdown: List[dict]
    reason: str
    risk_notes: List[str]
    data_confidence: str


class RecommendationOut(BaseModel):
    profile: ProfileOut
    total_groups: int
    冲_count: int
    稳_count: int
    保_count: int
    recommendations: List[RecommendationItem]
    special_recommendations: List[RecommendationItem] = []
    special_by_type: dict = {}
    warnings: List[str]


class ProvinceRuleOut(BaseModel):
    province: str
    province_code: Optional[str] = None
    enabled: bool = True
    score_mode: Optional[str] = None
    group_mode: Optional[str] = None
    batch: Optional[str] = None
    max_groups: int = 45
    max_majors_per_group: int = 6
    subject_types: List[str] = []
    cutoffs: dict = {}
    notes: Optional[str] = None


class SystemInfo(BaseModel):
    version: str
    backend_port: int
    province_rules: dict
