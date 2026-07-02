"""
OpenAI-compatible LLM client for Spiral.
Defaults to the WinCode endpoint; reads API key from WINCODE_API_KEY env var.
"""

import os
import json
import re
import time
import httpx
from typing import Dict, List, Optional


DEFAULT_BASE_URL = "https://wincode.winning.com.cn/ai/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


def _get_api_key() -> Optional[str]:
    return os.environ.get("WINCODE_API_KEY") or os.environ.get("OPENAI_API_KEY")


def _get_base_url() -> str:
    return os.environ.get("WINCODE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _is_retryable(exc: Exception) -> bool:
    """Transient failures that are worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError, httpx.ProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503, 504)
    return False


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = 60.0,
    tools: Optional[List[dict]] = None,
    max_retries: int = 2,
) -> dict:
    """
    Send a chat request and return the full message dict.
    Returns {"content": str, "tool_calls": [{"id": str, "function": {"name": str, "arguments": str}}]}
    没有配置 API key 时直接报错，不允许降级。
    对超时/网关错误做指数退避重试。
    """
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("LLM 未配置：未找到 WINCODE_API_KEY 或 OPENAI_API_KEY 环境变量")

    url = f"{_get_base_url()}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools

    # Use httpx with explicit timeout: 30s connect, requested read (LLM can be slow)
    t = httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
    last_exc: Optional[Exception] = None
    with httpx.Client(timeout=t) as client:
        for attempt in range(max_retries + 1):
            try:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
                return {
                    "content": (msg.get("content") or "").strip(),
                    "tool_calls": msg.get("tool_calls", []),
                }
            except Exception as exc:
                last_exc = exc
                if attempt == max_retries or not _is_retryable(exc):
                    raise
                wait = 2 ** attempt
                time.sleep(wait)
    # Should never reach here; raise the last captured exception.
    raise last_exc or RuntimeError("LLM 调用失败")


def _extract_excluded_tokens(text: str) -> List[str]:
    """从轻量规则提取排除专业关键词。"""
    if not text:
        return []
    m = re.search(r"(?:不想|不要|不考虑|排除|避开|不喜欢)[：:，,]?\s*([^\s，,。.；;]+)", text)
    if not m:
        return []
    raw = m.group(1)
    return [t.strip() for t in re.split(r"[、,，；;|/]", raw) if t.strip()]


def _rule_review(
    profile: Dict,
    recommendations: List[Dict],
    original_text: str,
) -> Dict:
    """快速规则质检，返回 severity/issues/auto_fixable。"""
    issues = []
    minor_issues = []
    level_order = {"冲": 0, "稳": 1, "保": 2}

    # 结构检查
    if len(recommendations) != 15:
        issues.append(f"推荐条目数量应为15条，实际{len(recommendations)}条")

    level_counts = {}
    for r in recommendations:
        level_counts[r.get("level", "")] = level_counts.get(r.get("level", ""), 0) + 1
    for lv in ["冲", "稳", "保"]:
        if level_counts.get(lv) != 5:
            issues.append(f"{lv}档应为5条，实际{level_counts.get(lv, 0)}条")

    # 位次排序检查
    by_level = {}
    for r in recommendations:
        by_level.setdefault(r.get("level", ""), []).append(r)
    for lv in ["冲", "稳", "保"]:
        ranks = [r.get("ref_rank") or 0 for r in by_level.get(lv, [])]
        if ranks and ranks != sorted(ranks):
            minor_issues.append(f"{lv}档位次未严格按升序排列")

    # 全局顺序检查：冲→稳→保
    levels = [r.get("level", "") for r in recommendations]
    expected_order = ["冲"] * 5 + ["稳"] * 5 + ["保"] * 5
    if levels != expected_order:
        issues.append("志愿表整体顺序不是冲→稳→保")

    # 排除项检查
    excluded = _extract_excluded_tokens(original_text)
    if profile.get("excluded_majors"):
        excluded += [t for t in re.split(r"[、,，；;|/]", profile["excluded_majors"]) if t.strip()]
    excluded = list(set(excluded))
    for r in recommendations:
        check_text = f"{r.get('school_name', '')} {r.get('group_code', '')} "
        majors = r.get("majors", [])
        if isinstance(majors, list):
            check_text += " ".join(str(m.get("name", "")) if isinstance(m, dict) else str(m) for m in majors)
        for tok in excluded:
            if tok and tok in check_text:
                issues.append(f"{r.get('school_name')} {r.get('group_code')} 包含排除项：{tok}")

    # 推荐理由长度检查
    short_reasons = 0
    for r in recommendations:
        reason = r.get("reason", "")
        if not reason or len(reason.strip()) < 15:
            short_reasons += 1
    if short_reasons:
        minor_issues.append(f"有{short_reasons}条推荐理由过短（<15字）")

    severity = "ok"
    if issues:
        severity = "major"
    elif minor_issues:
        severity = "minor"

    return {
        "severity": severity,
        "issues": issues + minor_issues,
        "major_issues": issues,
        "minor_issues": minor_issues,
    }


def _auto_fix_recommendations(recommendations: List[Dict]) -> List[Dict]:
    """对轻微问题进行本地修正（排序、截断过长理由等）。"""
    level_order = {"冲": 0, "稳": 1, "保": 2}
    sorted_recs = sorted(
        recommendations,
        key=lambda r: (level_order.get(r.get("level", ""), 3), r.get("ref_rank") or 0),
    )
    for r in sorted_recs:
        reason = r.get("reason", "")
        if reason and len(reason) > 200:
            r["reason"] = reason[:197] + "..."
    # 重新编号
    for i, r in enumerate(sorted_recs, 1):
        r["group_index"] = i
    return sorted_recs


def review_and_summarize(
    profile: Dict,
    recommendations: List[Dict],
    original_text: str,
    candidate_pool: List[Dict] = None,
) -> Dict:
    """轮2 质检：先规则快速检查，再调用轻量 LLM 做独立判断。
    ok / minor 尽量不二次生成 recommendations；major 返回 issues 供轮1重跑。

    返回: {
        "severity": "ok|minor|major",
        "recommendations": [...],
        "summary": "...",
        "issues": [...],
        "confidence": "high/medium/low"
    }
    """
    import json as _json

    # 1) 规则质检
    rule = _rule_review(profile, recommendations, original_text)

    # 规则完全通过且无明显问题：跳过 LLM 复审，直接使用轮1 的 summary
    if rule["severity"] == "ok" and not rule["issues"]:
        return {
            "severity": "ok",
            "recommendations": recommendations,
            "summary": "",
            "issues": [],
            "confidence": "high",
        }

    # major 直接返回问题，由 report.py 回退轮1重跑
    if rule["severity"] == "major":
        return {
            "severity": "major",
            "recommendations": recommendations,
            "summary": "规则质检发现严重问题，需回退轮1修正。",
            "issues": rule["issues"],
            "confidence": "low",
        }

    # 2) 轻量 LLM 独立复审（只输出 severity/summary/issues，不重新生成15条）
    rec_brief = []
    for r in recommendations:
        majors = r.get("majors", [])
        major_names = ", ".join(
            m.get("name", "") if isinstance(m, dict) else str(m) for m in majors[:3]
        )
        rec_brief.append(
            f"- [{r.get('level')}] {r.get('school_name')}({r.get('school_level') or '未知'}) "
            f"{r.get('group_code')} | 位次{r.get('ref_rank','?')} | 专业:{major_names}"
        )

    prompt = f"""考生原始诉求：{original_text}

轮1 LLM 已输出的志愿方案：
{chr(10).join(rec_brief)}

你是高考志愿填报复审专家，有自己独立的判断。请只做严格质检，不要输出新的 recommendations 数组。

质检维度：
1. 是否违反考生明确排除项（医学/土木/定向/预科等）
2. 层次利用是否合理（985/211/双一流是否被充分利用）
3. 位次排序是否按冲→稳→保、同档内位次从高到低
4. 专业方向是否与考生意向（理工/电工科）匹配
5. 推荐理由是否有独立判断而非套话

输出严格 JSON：
{{
  "severity": "ok/minor/major",
  "summary": "2-3句整体评价，体现你的独立判断",
  "issues": ["发现的问题（无则空数组）"]
}}
severity=ok 表示无需修改；severity=minor 表示有1-2处可本地微调；severity=major 表示必须回退轮1重跑。
只输出 JSON。"""

    resp = chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1024,
        timeout=90.0,
    )
    raw = resp["content"]
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        review = _json.loads(raw)
    except Exception:
        review = {"severity": "ok", "summary": raw or "复审LLM返回非JSON，已原样交付。", "issues": ["复审LLM返回非JSON，已原样交付"]}

    severity = review.get("severity", "ok")
    summary = review.get("summary", "")
    issues = review.get("issues", [])

    # 合并 LLM 发现的问题与规则问题
    all_issues = list(dict.fromkeys(rule["issues"] + issues))

    if severity == "major" or all_issues:
        # 只要 LLM 或规则认为有严重/轻微问题，统一交给 report.py 处理
        effective_severity = "major" if severity == "major" else ("minor" if all_issues else "ok")
    else:
        effective_severity = "ok"

    if effective_severity == "minor":
        fixed = _auto_fix_recommendations(recommendations)
        return {
            "severity": "minor",
            "recommendations": fixed,
            "summary": summary or "已按规则自动微调并提交。",
            "issues": all_issues,
            "confidence": "medium",
        }

    return {
        "severity": "ok",
        "recommendations": recommendations,
        "summary": summary or "方案通过复审。",
        "issues": all_issues,
        "confidence": "high",
    }
