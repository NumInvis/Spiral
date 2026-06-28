from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=True)
    province = Column(String(50), nullable=False)
    subject_type = Column(String(20), nullable=False)  # 物理 / 历史
    score = Column(Integer, nullable=False)
    rank = Column(Integer, nullable=False)
    preferred_major = Column(String(200), nullable=True)
    preferred_city = Column(String(200), nullable=True)
    strategy = Column(String(50), nullable=True, default=None)
    risk_preference = Column(String(20), nullable=True, default="balanced")
    accept_adjustment = Column(Boolean, default=True)
    allow_special_types = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    level = Column(String(50), nullable=True)  # 985 / 211 / 双一流 / 普通本科 / 公办 / 民办
    province = Column(String(50), nullable=True)
    city = Column(String(50), nullable=True)
    is_public = Column(Boolean, default=True)
    has_master = Column(Boolean, default=False)
    has_phd = Column(Boolean, default=False)
    category = Column(String(100), nullable=True)  # 综合 / 理工 / 师范 / 财经 / 医科 ...
    tags = Column(Text, nullable=True)  # 逗号分隔标签

    majors = relationship("Major", back_populates="school", cascade="all, delete-orphan")


class Major(Base):
    __tablename__ = "majors"

    id = Column(Integer, primary_key=True, index=True)
    school_id = Column(Integer, ForeignKey("schools.id"))
    code = Column(String(20), nullable=True)
    name = Column(String(200), nullable=False)
    group_code = Column(String(50), nullable=True, index=True)  # 院校专业组代码
    category = Column(String(100), nullable=True)  # 工科 / 理科 / 文科 / 医科 / 经管 / 艺术
    subject_require = Column(String(100), nullable=True)  # 选科要求，如 物化 / 物化生 / 史政地 / 不限
    duration = Column(Integer, default=4)
    tuition = Column(Integer, nullable=True)
    discipline_eval = Column(String(10), nullable=True)  # A+ / A / A- / B+ ...
    employment_score = Column(Float, default=0.0)
    description = Column(Text, nullable=True)

    school = relationship("School", back_populates="majors")
    scores = relationship("MajorScore", back_populates="major", cascade="all, delete-orphan")
    plans = relationship("AdmissionPlan", back_populates="major", cascade="all, delete-orphan")


class MajorScore(Base):
    __tablename__ = "major_scores"

    id = Column(Integer, primary_key=True, index=True)
    major_id = Column(Integer, ForeignKey("majors.id"))
    province = Column(String(50), nullable=False)
    subject_type = Column(String(20), nullable=False)
    year = Column(Integer, nullable=False)
    lowest_score = Column(Integer, nullable=True)
    avg_score = Column(Integer, nullable=True)
    highest_score = Column(Integer, nullable=True)
    lowest_rank = Column(Integer, nullable=True)
    # 专业真实录取线（当 CSV 提供时）；否则为 None
    major_lowest_score = Column(Integer, nullable=True)
    major_lowest_rank = Column(Integer, nullable=True)
    # 专业组投档线（组线），用于缺失专业线时估算
    group_lowest_score = Column(Integer, nullable=True)
    group_lowest_rank = Column(Integer, nullable=True)
    # 该条投档数据对应的院校专业组代码（不同年份组代码可能变化）
    group_code = Column(String(50), nullable=True, index=True)
    data_confidence = Column(String(10), default="A")  # A/B/C/D
    data_source = Column(String(200), nullable=True)

    major = relationship("Major", back_populates="scores")


class AdmissionPlan(Base):
    __tablename__ = "admission_plans"

    id = Column(Integer, primary_key=True, index=True)
    major_id = Column(Integer, ForeignKey("majors.id"))
    province = Column(String(50), nullable=False)
    subject_type = Column(String(20), nullable=False)
    year = Column(Integer, nullable=False)
    plan_count = Column(Integer, nullable=False, default=0)
    group_code = Column(String(50), nullable=True)

    major = relationship("Major", back_populates="plans")


class RankTable(Base):
    """各省一分一段表（score -> accumulate rank）。"""
    __tablename__ = "rank_tables"

    id = Column(Integer, primary_key=True, index=True)
    province = Column(String(50), nullable=False, index=True)
    subject_type = Column(String(20), nullable=False, index=True)  # 物理 / 历史 / 综合 ...
    year = Column(Integer, nullable=False, index=True)
    score = Column(Integer, nullable=False, index=True)  # 分数点（取区间上限）
    num = Column(Integer, nullable=True)                 # 该分数段人数
    accumulate = Column(Integer, nullable=True)          # 累计人数 / 最低位次
    source = Column(String(200), nullable=True)

    __table_args__ = {"sqlite_autoincrement": True}


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String(50), nullable=False, index=True)  # charter / major / employment / policy
    title = Column(String(300), nullable=False)
    school_name = Column(String(200), nullable=True, index=True)
    province = Column(String(50), nullable=True)
    source_url = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
