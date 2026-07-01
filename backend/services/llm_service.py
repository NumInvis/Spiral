"""
OpenAI-compatible LLM client for Spiral.
Defaults to the WinCode endpoint; reads API key from WINCODE_API_KEY env var.
"""

import os
import json
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
    if isinstance(exc, httpx.ConnectError):
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


def review_and_summarize(
    profile: Dict,
    recommendations: List[Dict],
    original_text: str,
    candidate_pool: List[Dict] = None,
) -> Dict:
    """轮2: LLM 独立质检。有自己的学校/专业/未来判断。
    轻微问题自行微调交付；严重不符回退让轮1重跑。

    candidate_pool: DB预筛选的完整候选池（供轮2替换时取用），结构同 recommendations 元素。
    返回: {
        "severity": "ok|minor|major",  # ok=直接交付, minor=已微调交付, major=回退轮1
        "recommendations": [...],       # 微调后的15条（minor时与输入可能不同）
        "summary": "...",               # 整体评价
        "issues": [...],                # 发现的问题
        "confidence": "high/medium/low"
    }
    """
    import json as _json

    # 轮1输出概要
    rec_brief = []
    for r in recommendations:
        rec_brief.append(
            f"- [{r.get('level')}] {r.get('school_name')}({r.get('school_level') or '未知'}) "
            f"{r.get('group_code')} | 组位次{r.get('ref_rank','?')} | "
            f"理由：{r.get('reason','')}"
        )

    # 备选候选池（供轮2替换用）
    pool_brief = []
    if candidate_pool:
        for r in candidate_pool:
            pool_brief.append(
                f"- [{r.get('level')}] {r.get('school_name')}({r.get('school_level') or '未知'}) "
                f"{r.get('group_code')} | 组位次{r.get('ref_rank','?')}"
            )

    prompt = f"""考生原始诉求：{original_text}

轮1 LLM 已输出的15条志愿方案：
{chr(10).join(rec_brief)}

备选候选池（你可从中替换，仅在严重不符时使用）：
{chr(10).join(pool_brief) if pool_brief else '无'}

你是高考志愿填报复审专家，有自己独立的判断。请对这份方案做严格质检：

## 你的独立判断维度
- 学校实力：985/211/双一流/普通本科的层次是否被合理利用
- 学科前景：专业是否有发展潜力、是否夕阳产业、是否与国家战略契合
- 就业导向：该校该专业的就业去向、行业薪资、地域产业匹配
- 位次排序：志愿表必须按位次从高到低排序（冲→稳→保），同档内也按位次降序。位次低的排在位次高的前面=志愿表作废，必须修正
- 诉求相符：是否违反考生明确排除项（医学/土木等）

## 质检结果分级（重要：能自己改就不要回退）
- ok：方案合理，直接交付
- minor：有1-2条需要微调（替换专业组、修正理由、调整顺序、修正位次排序），你自行修改后交付
- major：严重不符（多条违反排除项、结构坍塌、名校误判、位次排序混乱且无法局部修正），必须回退轮1重跑

## 你的权力
- minor 时你可以直接修改 recommendations 数组（替换条目、调整 reason、重排序修正位次），但必须保持5冲5稳5保共15条
- major 时不要修改 recommendations，只标注 issues 让系统回退轮1

输出严格 JSON：
```json
{{
  "severity": "ok/minor/major",
  "recommendations": [
    {{"level":"冲/稳/保","school_name":"...","school_code":"...","city":"...","group_code":"...","ref_rank":0,"majors":[{{"name":"...","relevance":0.0}}],"reason":"30-100字理由","data_confidence":"C","year_breakdown":[{{"year":2025,"rank":0,"score":0,"confidence":"C"}}]}}
  ],
  "summary": "2-3句整体评价，体现你的独立判断",
  "issues": ["发现的问题（无则空数组）"],
  "confidence": "high/medium/low"
}}
```
severity=ok 时 recommendations 可原样返回；severity=major 时 recommendations 原样返回不修改。
只输出 JSON。"""

    resp = chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4096,
        timeout=180.0,
    )
    raw = resp["content"]
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return _json.loads(raw)
    except Exception:
        return {
            "severity": "ok",
            "recommendations": recommendations,
            "summary": raw,
            "issues": ["复审LLM返回非JSON，已原样交付"],
            "confidence": "low",
        }
