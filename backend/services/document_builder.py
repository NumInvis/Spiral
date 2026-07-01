"""基于已导入的全量数据库构建 RAG 文档。

不再手写少量招生章程/专业解读，而是从以下真实数据自动生成：
- 各省志愿填报规则（province_rules/*.json）
- 院校库全量元数据（层次、城市、标签、招生计划汇总）
- 专业库全量记录（含 gaokao-zhiyuan SQL dump 中的官方专业说明、历年投档线、招生计划）
"""

from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from models import School, Major, MajorScore
from config.province_rules import PROVINCE_RULES, CURRENT_YEAR


def _join(items) -> str:
    return "、".join(str(x) for x in items if x)


def build_policy_documents() -> List[Dict]:
    """为每个已配置省份生成政策/规则文档。"""
    docs = []
    for province, rule in PROVINCE_RULES.items():
        score_mode = rule.get("score_mode", "")
        group_mode = rule.get("group_mode", "")
        max_groups = rule.get("max_groups", "")
        max_majors = rule.get("max_majors_per_group", "")
        batch = rule.get("batch", "")
        notes = rule.get("notes", "")
        data_sources = _join(rule.get("data_sources", []))

        cutoff_lines = []
        for year, subs in sorted(rule.get("cutoffs", {}).items(), reverse=True):
            for sub, vals in subs.items():
                line = f"{year}年{sub}："
                parts = [f"{k}{v}分" for k, v in vals.items()]
                cutoff_lines.append(line + "，".join(parts))

        content = (
            f"{province}省高考采用{score_mode}模式，{group_mode}投档，"
            f"{batch}最多可填报{max_groups}个院校专业组，每组最多{max_majors}个专业。\n"
            f"填报规则说明：{notes}\n"
            f"历年批次线：\n" + "\n".join(cutoff_lines) + "\n"
            f"数据来源：{data_sources}。以上信息仅供参考，请以各省招生考试机构官方发布为准。"
        )
        docs.append({
            "title": f"{province}省高考志愿填报规则与批次线",
            "doc_type": "policy",
            "province": province,
            "source_url": None,
            "content": content,
        })
    return docs


def build_school_document(school: School, db: Session) -> Optional[Dict]:
    """为单个院校生成事实文档。"""
    if not school.name:
        return None

    # 汇总该校的专业组、专业数、招生计划
    groups = set()
    major_names = []
    total_plan = 0
    for major in school.majors:
        if major.group_code:
            groups.add(major.group_code)
        major_names.append(major.name)
        for plan in major.plans:
            if plan.year == CURRENT_YEAR:
                total_plan += plan.plan_count or 0

    level = school.level or "普通本科"
    public = "公办" if school.is_public else "民办"
    category = school.category or "综合"
    city = school.city or school.province or "未知"
    tags = school.tags or ""

    content = (
        f"{school.name}（院校代码{school.code}）是一所{level}{public}{category}院校，"
        f"位于{city}。\n"
        f"院校标签：{tags}。\n"
        f"{CURRENT_YEAR}年在湖北本科批共设置{len(groups)}个院校专业组，"
        f"开设{_join(sorted(set(major_names)))}等专业，"
        f"招生计划合计约{total_plan}人。\n"
    )
    if school.has_phd:
        content += "学校具有博士学位授予权。"
    elif school.has_master:
        content += "学校具有硕士学位授予权。"

    return {
        "title": f"{school.name}院校概况与招生计划",
        "doc_type": "charter",
        "school_name": school.name,
        "province": school.province,
        "source_url": None,
        "content": content,
    }


def build_major_document(major: Major, db: Session) -> Optional[Dict]:
    """为单个专业生成事实文档。"""
    if not major.name or not major.school:
        return None

    school = major.school
    # 最新两年投档线
    score_lines = []
    latest_scores = (
        db.query(MajorScore)
        .filter(MajorScore.major_id == major.id)
        .order_by(MajorScore.year.desc())
        .limit(3)
        .all()
    )
    for s in latest_scores:
        parts = []
        if s.lowest_score:
            parts.append(f"最低分{s.lowest_score}")
        if s.lowest_rank:
            parts.append(f"最低位次{s.lowest_rank}")
        if parts:
            score_lines.append(f"{s.year}年{s.province}{s.subject_type}：" + "，".join(parts))

    # 最新招生计划
    plan_lines = []
    for p in major.plans:
        if p.year == CURRENT_YEAR and p.plan_count:
            plan_lines.append(f"{p.year}年{p.province}{p.subject_type}招生计划{p.plan_count}人")

    content_parts = [
        f"{school.name} {major.name}",
    ]
    if major.code:
        content_parts.append(f"专业代码{major.code}")
    if major.group_code:
        content_parts.append(f"所属院校专业组{major.group_code}")
    content_parts.append(f"选科要求{major.subject_require or '不限'}")
    content_parts.append(f"学制{major.duration or 4}年")
    if major.tuition:
        content_parts.append(f"学费{major.tuition}元/年")
    if major.category:
        content_parts.append(f"专业类别{major.category}")

    content = "，".join(content_parts) + "。\n"
    if major.description:
        content += f"专业说明：{major.description}\n"
    if score_lines:
        content += "历年录取：\n" + "\n".join(score_lines) + "\n"
    if plan_lines:
        content += "招生计划：\n" + "\n".join(plan_lines) + "\n"
    content += "数据来源于各省教育考试院投档线及招生计划公开数据，请以官方公布为准。"

    return {
        "title": f"{school.name} {major.name} 专业解读",
        "doc_type": "major",
        "school_name": school.name,
        "province": school.province,
        "source_url": None,
        "content": content,
    }


def build_all_documents(db: Session) -> List[Dict]:
    """构建全量 RAG 文档（政策 + 院校 + 专业）。"""
    docs: List[Dict] = []

    # 1. 各省规则
    docs.extend(build_policy_documents())

    # 2. 院校文档
    print("[rag] building school documents ...")
    schools = db.query(School).all()
    for school in schools:
        doc = build_school_document(school, db)
        if doc:
            docs.append(doc)

    # 3. 专业文档
    print(f"[rag] building major documents for {len(schools)} schools ...")
    majors = db.query(Major).all()
    for major in majors:
        doc = build_major_document(major, db)
        if doc:
            docs.append(doc)

    print(f"[rag] total documents: {len(docs)}")
    return docs
