"""
Spiral ReAct Agent — 推理循环

LLM 全程决策：每轮选择调用什么工具，拿到结果后继续推理，
直到输出最终推荐方案。
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, selectinload

from models import School, Major, MajorScore, RankTable
from config.province_rules import LATEST_HISTORICAL_YEAR
from services.llm_service import chat_completion
from agent_tools import all_tools, get_tool, tools_for_openai
from services.major_matcher import build_major_intent, score_major_relevance


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
    profile: Optional[Dict] = None
    selected: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    trace: List[AgentStep] = field(default_factory=list)
    final_result: Optional[Dict] = None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是 Spiral 高考志愿填报 Agent。你的任务是根据考生的自然语言描述，通过调用工具查询数据库，经过多轮推理，最终输出一份完整的志愿推荐方案。

## 工作流程

1. **解析画像**：从用户描述中提取省份、科类、位次、意向专业、意向城市、风险偏好
2. **扩展专业意向**：调用 expand_major_intent 将用户意向扩展为关键词和学科门类
3. **查询候选池**：调用 query_score_lines 查询该省该科类的院校专业组投档线
4. **估算概率**：对候选专业组调用 estimate_probability 计算录取概率
5. **过滤特殊类型**：调用 filter_special_types 排除特殊类型招生（除非用户明确接受）
6. **等位分换算**：如有上一年数据，调用 get_equivalent_rank 做跨年修正
7. **综合排序**：按冲/稳/保分档，输出最终推荐

## 最终输出格式

当你完成所有工具调用和推理后，输出最终的推荐方案 JSON：

```json
{
  "profile": {
    "province": "湖北",
    "subject_type": "物理",
    "rank": 25000,
    "score": 580,
    "preferred_major": "计算机、电子信息",
    "preferred_city": "武汉、上海",
    "risk_preference": "balanced",
    "allow_special_types": false
  },
  "recommendations": [
    {
      "group_index": 1,
      "level": "冲",
      "school_name": "武汉理工大学",
      "school_code": "W02",
      "city": "武汉",
      "group_code": "W0201",
      "probability": 0.35,
      "ref_rank": 22000,
      "year_breakdown": [
        {"year": 2025, "rank": 22000, "score": 590, "confidence": "C"},
        {"year": 2024, "rank": 23500, "score": 585, "confidence": "C"}
      ],
      "majors": [
        {"name": "计算机科学与技术", "relevance": 0.92, "probability": 0.35},
        {"name": "软件工程", "relevance": 0.88, "probability": 0.38}
      ],
      "reason": "该校计算机学科实力强，位次匹配冲档",
      "data_confidence": "C"
    }
  ],
  "warnings": ["以上推荐基于组线估算，实际专业线可能更高"]
}
```

## 关键规则
1. **第一轮必须调用 expand_major_intent** 扩展你的专业意向
2. **第二轮必须调用 query_score_lines** 查询候选池
3. **对感兴趣的候选调用 estimate_probability** 估算录取概率
4. **数据收集完毕后（最多 5-7 轮），必须立即输出最终 JSON 推荐方案**
5. 如果某次工具调用失败，换一种参数重试，不要放弃
6. 禁止超过 8 轮仍未输出最终方案 — 即使数据不完整也必须给出你能给出的最佳推荐
"""


def _post_process(state: AgentState, db: Session) -> None:
    """Enrich agent output with database fields the LLM might not have."""
    if not state.final_result:
        return

    recs = state.final_result.get("recommendations", [])
    for i, rec in enumerate(recs, 1):
        # Ensure group_index
        rec.setdefault("group_index", i)

        # Look up school from DB for missing fields
        school_name = rec.get("school_name", "")
        school = db.query(School).filter(School.name == school_name).first() if school_name else None

        if school:
            rec.setdefault("school_code", school.code)
            rec.setdefault("city", school.city)

        # Build year_breakdown if missing
        if not rec.get("year_breakdown"):
            ref_rank = rec.get("ref_rank")
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

        # Ensure majors have required fields
        majors = rec.get("majors", [])
        if isinstance(majors, list):
            enriched = []
            for m in majors:
                if isinstance(m, str):
                    enriched.append({"name": m, "relevance": 0.5, "probability": rec.get("probability", 0.5)})
                elif isinstance(m, dict):
                    m.setdefault("relevance", 0.5)
                    m.setdefault("probability", rec.get("probability", 0.5))
                    enriched.append(m)
            rec["majors"] = enriched[:6]

        rec.setdefault("risk_notes", [])
        rec.setdefault("data_confidence", "C")

    state.final_result["recommendations"] = recs
    state.selected = recs


# ---------------------------------------------------------------------------
# ReAct loop
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
    # Try to find JSON object in the response
    patterns = [
        r'```json\s*(\{.*?\})\s*```',
        r'```\s*(\{.*?\})\s*```',
        r'(\{\s*"profile"\s*:.*?"recommendations"\s*:.*?\})',
    ]
    for pat in patterns:
        m = re.search(pat, content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return None


def run_agent(
    text: str,
    db: Session,
    rank: Optional[int] = None,
    province: Optional[str] = None,
    max_iterations: int = 10,
) -> AgentState:
    """
    ReAct Agent: 两阶段架构
    Phase 1 — LLM 规划 + 工具调用（收集数据）
    Phase 2 — LLM 综合推理（输出最终推荐）
    """
    state = AgentState(original_text=text, rank=rank, province=province)

    # ── Phase 1: 数据收集 ──────────────────────────────────────────────
    # 用固定流程收集核心数据，不做 LLM 决策
    collect_step = _add_step(state, "数据收集", status="running")

    # 1. 解析画像
    profile_data = _parse_profile_llm(text, rank, province)
    state.profile = profile_data
    collect_step.output_summary = f"画像: {profile_data.get('province')} {profile_data.get('subject_type')} 位次{profile_data.get('rank')}"

    # 2. 查询候选池
    candidates = _query_candidates(db, profile_data)
    collect_step.output_summary += f" | 候选池: {len(candidates)} 条"

    # 3. 专业意向扩展
    intent = _expand_intent(profile_data.get("preferred_major"))

    # 4. 概率估算 + 分档
    scored = _score_candidates(candidates, profile_data, intent, db)
    collect_step.output_summary += f" | 评分后: {len(scored)} 条"
    collect_step.status = "done"

    # ── Phase 2: LLM 综合推理 ──────────────────────────────────────────
    # 将所有数据交给 LLM，让它做最终决策
    reasoning_step = _add_step(state, "LLM 综合推理", status="running")

    final = _llm_final_reasoning(state, scored, profile_data, intent)

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
# Phase 1 helpers
# ---------------------------------------------------------------------------

def _parse_profile_llm(text: str, rank: Optional[int], province: Optional[str]) -> Dict:
    """Use LLM to parse profile from free text."""
    from services.profile_parser import parse_free_text
    profile = parse_free_text(text, rank=rank, province=province)
    return {
        "province": profile.province,
        "subject_type": profile.subject_type,
        "rank": profile.rank,
        "score": profile.score,
        "preferred_major": profile.preferred_major,
        "preferred_city": profile.preferred_city,
        "risk_preference": profile.risk_preference,
        "allow_special_types": profile.allow_special_types,
    }


def _query_candidates(db: Session, profile: Dict) -> List[Dict]:
    """Query candidate major groups from database."""
    province = profile.get("province", "")
    subject_type = profile.get("subject_type", "")
    year = LATEST_HISTORICAL_YEAR

    rows = (
        db.query(MajorScore)
        .join(Major)
        .join(School)
        .filter(
            MajorScore.province == province,
            MajorScore.subject_type == subject_type,
            MajorScore.year == year,
            MajorScore.group_lowest_rank.isnot(None),
        )
        .options(selectinload(MajorScore.major).selectinload(Major.school))
        .limit(500)
        .all()
    )

    candidates = []
    for ms in rows:
        candidates.append({
            "school_name": ms.major.school.name,
            "school_level": ms.major.school.level,
            "school_city": ms.major.school.city,
            "major_name": ms.major.name,
            "group_code": ms.group_code or ms.major.group_code or "01",
            "group_lowest_rank": ms.group_lowest_rank,
            "group_lowest_score": ms.group_lowest_score,
            "data_confidence": ms.data_confidence,
        })

    # Also query prev year for cross-year analysis
    prev_rows = (
        db.query(MajorScore)
        .join(Major)
        .join(School)
        .filter(
            MajorScore.province == province,
            MajorScore.subject_type == subject_type,
            MajorScore.year == year - 1,
            MajorScore.group_lowest_rank.isnot(None),
        )
        .limit(500)
        .all()
    )
    prev_index = {}
    for ms in prev_rows:
        key = (ms.major.school.name, ms.group_code or ms.major.group_code or "01")
        prev_index[key] = ms.group_lowest_rank

    for c in candidates:
        key = (c["school_name"], c["group_code"])
        c["prev_rank"] = prev_index.get(key)

    return candidates


def _expand_intent(preferred_major: Optional[str]) -> Dict:
    """Expand major preference into keywords and categories."""
    if not preferred_major:
        return {"keywords": [], "categories": [], "raw": ""}
    return build_major_intent(preferred_major)


def _score_candidates(
    candidates: List[Dict],
    profile: Dict,
    intent: Dict,
    db: Session,
) -> List[Dict]:
    """Score and rank candidates by probability and relevance."""
    rank = profile.get("rank", 0)
    if rank <= 0:
        return []

    risk = profile.get("risk_preference", "balanced")
    # Define probability thresholds per risk preference
    if risk == "aggressive":
        冲_range, 稳_range, 保_min = (0.05, 0.30), (0.30, 0.60), 0.60
    elif risk == "conservative":
        冲_range, 稳_range, 保_min = (0.20, 0.45), (0.55, 0.85), 0.85
    else:
        冲_range, 稳_range, 保_min = (0.15, 0.45), (0.45, 0.75), 0.75

    scored = []
    for c in candidates:
        ref_rank = c.get("group_lowest_rank")
        if not ref_rank or ref_rank <= 0:
            continue

        # Cross-year adjustment
        prev_rank = c.get("prev_rank")
        if prev_rank:
            ref_rank = int((ref_rank + prev_rank) / 2)

        prob = _calc_probability(rank, ref_rank)

        # Filter by probability (don't include very low probability)
        if prob < 0.05:
            continue

        # Relevance
        relevance, reason = score_major_relevance(c["major_name"], None, intent)

        # Determine level
        if 冲_range[0] <= prob < 冲_range[1]:
            level = "冲"
        elif 稳_range[0] <= prob < 稳_range[1]:
            level = "稳"
        elif prob >= 保_min:
            level = "保"
        else:
            level = "冲"  # edge case

        # Sort key: probability * 10 + relevance * 5
        sort_score = prob * 10 + relevance * 5

        scored.append({
            **c,
            "probability": prob,
            "ref_rank": ref_rank,
            "relevance": relevance,
            "level": level,
            "sort_score": sort_score,
        })

    # Sort within each level
    for level_name in ["冲", "稳", "保"]:
        level_items = [s for s in scored if s["level"] == level_name]
        level_items.sort(key=lambda x: x["sort_score"], reverse=True)
        # Deduplicate: max 2 groups per school
        school_counts = {}
        deduped = []
        for item in level_items:
            sn = item["school_name"]
            school_counts[sn] = school_counts.get(sn, 0) + 1
            if school_counts[sn] <= 2:
                deduped.append(item)
        # Limit per level
        if level_name == "冲":
            deduped = deduped[:10]
        elif level_name == "稳":
            deduped = deduped[:25]
        else:
            deduped = deduped[:10]
        # Replace in scored
        scored = [s for s in scored if s["level"] != level_name] + deduped

    return scored


def _calc_probability(candidate_rank: int, ref_rank: int) -> float:
    """Pure function for probability estimation."""
    if ref_rank <= 0:
        return 0.5
    rank_ratio = candidate_rank / ref_rank
    prob = 1.0 / (1.0 + max(0, rank_ratio - 0.85) * 4.0)
    return max(0.02, min(0.99, prob))


# ---------------------------------------------------------------------------
# Phase 2: LLM final reasoning
# ---------------------------------------------------------------------------

def _llm_final_reasoning(
    state: AgentState,
    scored: List[Dict],
    profile: Dict,
    intent: Dict,
) -> Optional[Dict]:
    """Give all collected data to LLM and ask for final structured recommendation."""
    if not scored:
        return None

    # Build summary for LLM
    profile_summary = (
        f"省份: {profile.get('province')}\n"
        f"科类: {profile.get('subject_type')}\n"
        f"位次: {profile.get('rank')}\n"
        f"意向专业: {profile.get('preferred_major') or '无'}\n"
        f"意向城市: {profile.get('preferred_city') or '无'}\n"
        f"风险偏好: {profile.get('risk_preference', 'balanced')}\n"
        f"扩展专业关键词: {', '.join(intent.get('keywords', []))}\n"
    )

    # Group by level
    by_level = {"冲": [], "稳": [], "保": []}
    for s in scored:
        by_level.setdefault(s["level"], []).append(s)

    # Compact candidate summary (top 5 per level)
    candidate_lines = []
    for level_name in ["冲", "稳", "保"]:
        items = by_level.get(level_name, [])[:5]
        candidate_lines.append(f"\n## {level_name}档候选（前10条）：")
        for item in items:
            candidate_lines.append(
                f"- {item['school_name']} {item['group_code']} | "
                f"专业:{item['major_name']} | "
                f"位次:{item['group_lowest_rank']} | "
                f"概率:{item['probability']:.0%} | "
                f"相关度:{item['relevance']:.2f} | "
                f"城市:{item.get('school_city', '未知')}"
            )

    prompt = f"""基于以下考生画像和候选数据，输出最终的志愿推荐方案。

{profile_summary}
{''.join(candidate_lines)}

请从候选中选择最优组合（冲10条、稳25条、保10条），每个学校最多2个组。

输出严格 JSON：
```json
{{
  "profile": {{"province":"{profile.get('province')}","subject_type":"{profile.get('subject_type')}","rank":{profile.get('rank')},"preferred_major":"{profile.get('preferred_major') or ''}","preferred_city":"{profile.get('preferred_city') or ''}","risk_preference":"{profile.get('risk_preference','balanced')}"}},
  "recommendations": [
    {{"level":"冲/稳/保","school_name":"...","school_code":"...","city":"...","group_code":"...","probability":0.0,"ref_rank":0,"majors":[{{"name":"...","relevance":0.0}}],"reason":"...","data_confidence":"C","year_breakdown":[{{"year":2025,"rank":0,"score":0,"confidence":"C"}}]}}
  ],
  "warnings":["提示1"]
}}
```
只输出 JSON，不要解释。"""

    result = chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=4096,
        timeout=300.0,
    )
    parsed = _parse_final_result(result["content"])
    if not parsed:
        raise RuntimeError("LLM 返回内容无法解析为有效 JSON")
    return parsed
