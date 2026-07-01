"""
Spiral Agent 推理循环（2轮 LLM 架构）

DB  — build_recommendation 预过滤+分档（特殊类型/排除专业/位次比例分档/跨年year_breakdown）
轮1 — LLM 综合决策：候选池 + 用户原文 → 自由排序/名校判断/排除医学/生成理由
轮2 — LLM 报告总结：原文 + 方案 → 总结语（在 report.py 调用）

科类/省份/位次由前端结构化传入，不再用 LLM 解析。
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from models import Profile, School, Major, MajorScore
from config.province_rules import LATEST_HISTORICAL_YEAR
from services.llm_service import chat_completion
from recommendation import build_recommendation


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

@dataclass
class AgentStep:
    step: int
    name: str
    status: str = "running"
    input_summary: str = ""
    output_summary: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    original_text: str
    rank: Optional[int] = None
    province: Optional[str] = None
    subject_type: Optional[str] = None
    profile: Optional[Dict] = None
    selected: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    trace: List[AgentStep] = field(default_factory=list)
    final_result: Optional[Dict] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_step(state: AgentState, name: str, status: str = "running",
              input_summary: str = "", output_summary: str = "",
              details: Dict[str, Any] = None) -> AgentStep:
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


def _parse_final_result(content: str) -> Optional[Dict]:
    """Try to parse the final JSON result from LLM response."""
    patterns = [
        r'```json\s*(\{.*\})\s*```',
        r'```\s*(\{.*\})\s*```',
        r'(\{[\s\S]*?"recommendations"[\s\S]*?\})',
    ]
    for pat in patterns:
        m = re.search(pat, content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(content.strip().strip("`").replace("json", "", 1).strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_agent(
    text: str,
    db: Session,
    rank: Optional[int] = None,
    province: Optional[str] = None,
    subject_type: Optional[str] = None,
    max_iterations: int = 10,
) -> AgentState:
    """
    2轮 LLM 架构（轮2在 report.py 调用）。
    科类/省份/位次由前端结构化传入，不用 LLM 解析。
    """
    state = AgentState(original_text=text, rank=rank, province=province, subject_type=subject_type)

    # ── DB预过滤+分档（复用 recommendation.py 完整逻辑）────────────────
    collect_step = _add_step(state, "数据收集", status="running")
    profile_obj, profile_data = _build_profile(text, rank, province, subject_type)
    state.profile = profile_data
    collect_step.output_summary = (
        f"画像: {profile_data.get('province')} {profile_data.get('subject_type')} "
        f"位次{profile_data.get('rank')}"
    )

    rec_result = build_recommendation(profile_obj, db)
    scored = rec_result["recommendations"]
    collect_step.output_summary += (
        f" | 候选池: {len(scored)} 条 "
        f"(冲{rec_result['冲_count']}/稳{rec_result['稳_count']}/保{rec_result['保_count']})"
    )
    collect_step.status = "done"

    # ── 轮1: LLM 主体决策 ──────────────────────────────────────────────
    reasoning_step = _add_step(state, "轮1 LLM 主体决策", status="running")
    final = _llm_final_reasoning(state, scored, profile_data)

    if final:
        state.final_result = final
        state.profile = final.get("profile", profile_data)
        state.selected = final.get("recommendations", [])
        state.warnings = final.get("warnings", [])
        _post_process(state, db)
        reasoning_step.status = "done"
        reasoning_step.output_summary = f"输出 {len(state.selected)} 条推荐"
    else:
        raise RuntimeError("LLM 推理层未返回有效结果")

    return state


# ---------------------------------------------------------------------------
# 画像构造（纯结构化，无 LLM）
# ---------------------------------------------------------------------------

def _build_profile(
    text: str,
    rank: Optional[int],
    province: Optional[str],
    subject_type: Optional[str],
) -> tuple:
    """从前端结构化字段构造 Profile；intent/excluded 从原文用规则提取。"""
    # 从原文规则提取意向专业/排除专业/风险偏好（不调 LLM）
    preferred_major = _extract_preferred_major(text)
    excluded_majors = _extract_excluded(text)
    risk_preference = _detect_risk(text)

    if not province:
        raise ValueError("缺少省份")
    if subject_type not in ("物理", "历史"):
        raise ValueError("科类必须为物理或历史")
    if not rank or rank <= 0:
        raise ValueError("位次必须为正整数")

    profile_data = {
        "province": province,
        "subject_type": subject_type,
        "rank": rank,
        "score": 0,
        "preferred_major": preferred_major,
        "preferred_city": None,
        "excluded_majors": excluded_majors,
        "risk_preference": risk_preference,
        "allow_special_types": False,
    }

    profile_obj = Profile(
        province=province,
        subject_type=subject_type,
        score=0,
        rank=rank,
        preferred_major=preferred_major,
        preferred_city=None,
        excluded_majors=excluded_majors,
        risk_preference=risk_preference,
        allow_special_types=False,
    )
    return profile_obj, profile_data


def _extract_preferred_major(text: str) -> Optional[str]:
    """从原文规则提取意向专业（轻量关键词识别，不调 LLM）。"""
    m = re.search(r"(?:想学|意向|偏好|最好|优先|喜欢)[：:，,]?\s*([^\s，,。.；;]+)", text)
    if m:
        return m.group(1).strip()
    return None


def _extract_excluded(text: str) -> Optional[str]:
    """从原文规则提取排除专业方向。"""
    m = re.search(r"(?:不想|不要|不考虑|排除|避开|不喜欢)[：:，,]?\s*([^\s，,。.；;]+)", text)
    if m:
        return m.group(1).strip()
    return None


def _detect_risk(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["激进", "多冲", "赌", "捡漏", "冲刺"]):
        return "aggressive"
    if any(k in t for k in ["保守", "求稳", "保稳", "避免滑档", "稳妥", "稳为主", "安全第一"]):
        return "conservative"
    return "balanced"


# ---------------------------------------------------------------------------
# 轮1: LLM 主体决策（每条30-100字理由，5冲5稳5保）
# ---------------------------------------------------------------------------

def _llm_final_reasoning(
    state: AgentState,
    scored: List,
    profile: Dict,
) -> Optional[Dict]:
    """轮1: 候选池 + 用户原始诉求 → LLM 主体决策，每条志愿30-100字理由。
    支持 state._review_feedback（轮2回退意见）和 state._retry_candidates（重跑候选）。"""
    # 重跑场景：scored 为空时用缓存候选
    candidates = scored if scored else getattr(state, "_retry_candidates", [])
    if not candidates:
        return None

    by_level = {"冲": [], "稳": [], "保": []}
    for s in candidates:
        by_level.setdefault(getattr(s, "level", ""), []).append(s)

    # 缓存候选供轮2回退时复用
    state._retry_candidates = candidates

    ratio_hint = {"冲": "50%-90%", "稳": "90%-110%", "保": "110%-130%"}
    candidate_lines = []
    for level_name in ["冲", "稳", "保"]:
        items = by_level.get(level_name, [])
        candidate_lines.append(f"\n## {level_name}档候选（{len(items)}条，位次比例{ratio_hint[level_name]}）：")
        for item in items:
            top_majors = []
            for m in (getattr(item, "majors", []) or [])[:3]:
                if isinstance(m, dict):
                    top_majors.append(m.get("name", ""))
                else:
                    top_majors.append(getattr(m, "name", ""))
            yb = getattr(item, "year_breakdown", []) or []
            ref_rank = yb[0].get("rank") if yb and isinstance(yb[0], dict) else "?"
            candidate_lines.append(
                f"- [{getattr(item,'group_code','')}] {getattr(item,'school_name','')}({getattr(item,'school_level','') or '未知'}) | "
                f"组位次{ref_rank} | 专业: {', '.join(top_majors)} | "
                f"城市:{getattr(item,'city','') or '未知'}"
            )

    # 轮2回退意见
    feedback_block = ""
    feedback = getattr(state, "_review_feedback", None)
    if feedback:
        feedback_block = f"""

## ⚠️ 上一轮复审反馈（必须修正）
上一轮方案被复审判定为严重不符，具体问题：
{chr(10).join(f'- {i}' for i in feedback)}
请在本次方案中彻底修正这些问题，不要重蹈覆辙。
"""

    prompt = f"""考生原始诉求：{state.original_text}

数据库已按位次比例预筛选候选池（每档5条，已过滤特殊类型与排除专业）：
{''.join(candidate_lines)}{feedback_block}

你是高考志愿填报首席专家，请对候选做主体决策。你必须有自己的独立判断：

## 你的判断维度
- 学校实力：985/211/双一流/普通本科的层次是否被合理利用，名校光环 vs 学科实力如何权衡
- 学科前景：专业是否有发展潜力、是否夕阳产业、是否与国家战略（芯片/AI/新能源/生物医药等）契合
- 就业导向：该校该专业的就业去向、行业薪资、地域产业匹配
- 专业匹配：与考生意向专业的相关度，大类招生能否分流到心仪方向
- 地域匹配：是否符合考生的城市偏好，异地求学成本与收益
- 位次梯度：冲稳保位次比例是否合理，有无捡漏机会或滑档风险

## 决策规则
- 严格基于考生原始诉求判断每条志愿适配度
- 若某条候选与考生诉求严重不符（如医学实验班但考生明确排除医学），可替换为同档更优项
- 必须保持5冲5稳5保共15条
- **志愿表必须按位次从高到低排序**：冲档在前（学校位次远高于考生）、稳档居中、保档在后（学校位次略低于考生）。同档内也按位次降序。绝不能把位次低的学校排在位次高的前面，否则志愿表作废
- 每条志愿必须给出 30-100 字的推荐理由，体现你对该校该专业的独立判断（不要套话、不要提"录取概率"）

输出严格 JSON：
```json
{{
  "recommendations": [
    {{"level":"冲/稳/保","school_name":"...","school_code":"...","city":"...","group_code":"...","ref_rank":0,"majors":[{{"name":"...","relevance":0.0}}],"reason":"30-100字推荐理由，体现你的独立判断","data_confidence":"C","year_breakdown":[{{"year":2025,"rank":0,"score":0,"confidence":"C"}}]}}
  ],
  "warnings":["针对该考生的风险提示，0-3条"]
}}
```
只输出 JSON。"""

    result = chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
        timeout=180.0,
    )
    parsed = _parse_final_result(result["content"])
    if not parsed:
        raise RuntimeError("LLM 返回内容无法解析为有效 JSON")
    return parsed


# ---------------------------------------------------------------------------
# 后处理：补全 DB 字段
# ---------------------------------------------------------------------------

def _post_process(state: AgentState, db: Session) -> None:
    """Enrich agent output with database fields; 强制按位次从高到低排序。"""
    if not state.final_result:
        return

    recs = state.final_result.get("recommendations", [])

    # 补全 DB 字段
    for rec in recs:
        school_name = rec.get("school_name", "")
        school = db.query(School).filter(School.name == school_name).first() if school_name else None
        if school:
            rec.setdefault("school_code", school.code)
            rec.setdefault("city", school.city)
            rec.setdefault("school_level", school.level)

        if not rec.get("year_breakdown"):
            province = state.profile.get("province", "") if state.profile else ""
            subject_type = state.profile.get("subject_type", "") if state.profile else ""
            year_breakdown = []
            if province and subject_type:
                for yr in [LATEST_HISTORICAL_YEAR, LATEST_HISTORICAL_YEAR - 1]:
                    score_row = (
                        db.query(MajorScore)
                        .join(Major)
                        .join(School)
                        .filter(
                            School.name == school_name,
                            MajorScore.province == province,
                            MajorScore.subject_type == subject_type,
                            MajorScore.year == yr,
                            MajorScore.group_lowest_rank.isnot(None),
                        )
                        .first()
                    )
                    if score_row:
                        year_breakdown.append({
                            "year": yr,
                            "rank": score_row.group_lowest_rank,
                            "score": score_row.group_lowest_score,
                            "confidence": score_row.data_confidence,
                        })
            rec["year_breakdown"] = year_breakdown

        # 用 year_breakdown 的最新年位次补全 ref_rank
        if not rec.get("ref_rank") and rec.get("year_breakdown"):
            rec["ref_rank"] = rec["year_breakdown"][0].get("rank")

        majors = rec.get("majors", [])
        if isinstance(majors, list):
            enriched = []
            for m in majors:
                if isinstance(m, str):
                    enriched.append({"name": m, "relevance": 0.5})
                elif isinstance(m, dict):
                    m.setdefault("relevance", 0.5)
                    enriched.append(m)
            rec["majors"] = enriched[:6]

        rec.setdefault("risk_notes", [])
        rec.setdefault("data_confidence", "C")

    # 强制按位次从高到低排序：冲→稳→保，同档内按 ref_rank 升序（ref_rank 小=学校强=排前）
    level_order = {"冲": 0, "稳": 1, "保": 2}
    def _sort_key(r):
        lv = level_order.get(r.get("level", ""), 3)
        ref = r.get("ref_rank") or 0
        return (lv, ref)
    recs.sort(key=_sort_key)

    # 重新编号 group_index
    for i, rec in enumerate(recs, 1):
        rec["group_index"] = i

    state.final_result["recommendations"] = recs
    state.selected = recs

