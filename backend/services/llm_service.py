"""
OpenAI-compatible LLM client for Spiral.
Defaults to the WinCode endpoint; reads API key from WINCODE_API_KEY env var.
"""

import os
import json
from typing import List, Dict, Optional
import httpx


DEFAULT_BASE_URL = "https://wincode.winning.com.cn/ai/v1"
DEFAULT_MODEL = "deepseek-v4-flash"


def _get_api_key() -> Optional[str]:
    return os.environ.get("WINCODE_API_KEY") or os.environ.get("OPENAI_API_KEY")


def _get_base_url() -> str:
    return os.environ.get("WINCODE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> str:
    """
    Send a chat request and return the assistant's text content.
    Falls back to a placeholder string if no API key is configured.
    """
    api_key = _get_api_key()
    if not api_key:
        return "[LLM 未配置：未找到 WINCODE_API_KEY 或 OPENAI_API_KEY 环境变量]"

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

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def parse_profile_with_llm(text: str, rank: Optional[int] = None) -> Dict:
    """
    Use LLM to extract structured profile fields from free-text description.
    Returns a dict compatible with ProfileCreate (keys: province, subject_type,
    score, rank, preferred_major, preferred_city, strategy, allow_special_types, notes).
    """
    system_prompt = (
        "你是 Spiral 高考志愿填报系统的画像解析专家。请从用户的自然语言描述中提取结构化信息，"
        "输出严格的 JSON 对象，不要任何解释。JSON 字段如下：\n"
        "- province: 省份，未说明则默认\"湖北\"\n"
        "- subject_type: \"物理\" 或 \"历史\"\n"
        "- score: 高考分数整数，无法提取填 0\n"
        "- rank: 全省位次整数\n"
        "- preferred_major: 意向专业，多个用顿号分隔，没有填 null\n"
        "- preferred_city: 意向城市，多个用顿号分隔，没有填 null\n"
        "- strategy: 必填，从 school/major/city/employment/academic/balanced 中选一个\n"
        "- allow_special_types: 是否明确提及国家专项/地方专项/高校专项/预科/定向/民族班/援藏/南疆/边防军人子女，布尔值\n"
        "- notes: 原始描述摘要\n"
        "strategy 判断规则：提到学校层次/985/211/名校 → school；提到兴趣/想学/专业壁垒 → major；"
        "提到城市/地域/留在 → city；提到就业/薪资/考公 → employment；提到考研/保研/深造 → academic；"
        "都不明显 → balanced。"
    )
    user_content = f"用户描述：{text}\n"
    if rank is not None:
        user_content += f"用户提供的位次：{rank}\n"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw = chat_completion(messages, temperature=0.2, max_tokens=512)
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    parsed = json.loads(raw)

    # Enforce required fields and fallbacks
    parsed.setdefault("province", "湖北")
    parsed.setdefault("subject_type", "物理")
    parsed.setdefault("score", 0)
    parsed.setdefault("rank", rank)
    parsed.setdefault("preferred_major", None)
    parsed.setdefault("preferred_city", None)
    parsed.setdefault("strategy", "balanced")
    parsed["accept_adjustment"] = True
    parsed.setdefault("allow_special_types", False)
    parsed.setdefault("notes", text)

    # If LLM didn't extract rank but user provided it, use it
    if parsed.get("rank") is None and rank is not None:
        parsed["rank"] = rank

    return parsed


def evaluate_major_match_with_llm(major_name: str, preferred_majors: Optional[List[str]]) -> Optional[Dict]:
    """
    使用 LLM 判断单个专业与考生意向专业的相关度。
    返回 {"score": 0.0-1.0, "reason": "一句话理由"}；无 API Key 或调用失败返回 None。
    """
    api_key = _get_api_key()
    if not api_key:
        return None
    if not preferred_majors:
        return None

    system_prompt = (
        "你是高考志愿专业匹配评估专家。请根据考生意向专业和待评估专业名称，"
        "判断两者相关程度并给出 0-1 之间的分数。只输出 JSON，不要解释。\n"
        "评分标准：\n"
        "- 0.85-1.0：专业名称直接对应或强相关（如计算机 ↔ 软件工程、人工智能）\n"
        "- 0.60-0.84：同属一个大类或高度相关（如电子信息 ↔ 通信工程、微电子）\n"
        "- 0.30-0.59：部分相关或需入学后分流的大类/试验班\n"
        "- 0.00-0.29：明显不相关（如护理 ↔ 计算机、采矿 ↔ 金融）\n"
        "输出格式：{\"score\": float, \"reason\": \"string\"}"
    )
    user_prompt = (
        f"考生意向专业：{'、'.join(preferred_majors)}\n"
        f"待评估专业：{major_name}\n"
        "请输出 JSON。"
    )
    try:
        raw = chat_completion(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.2,
            max_tokens=128,
        )
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        score = float(parsed.get("score", 0.5))
        score = max(0.0, min(1.0, score))
        return {"score": score, "reason": parsed.get("reason", "")}
    except Exception as e:
        print(f"[llm_service] evaluate_major_match failed ({e})")
        return None


def generate_report_summary(profile: Dict, result: Dict) -> str:
    """Generate a one-paragraph personalized summary for the HTML report."""
    system_prompt = (
        "你是 Spiral 高考志愿填报报告撰写专家。请根据考生画像和推荐方案，"
        "用 2-3 句话生成一段面向考生/家长的总结，风格专业、克制、有温度。"
        "不要出现任何无法验证的数据，不要承诺录取结果。"
    )
    user_prompt = (
        f"考生画像：{json.dumps(profile, ensure_ascii=False)}\n"
        f"推荐概况：共 {result.get('total_groups', 0)} 个院校专业组，"
        f"冲 {result.get('冲_count', 0)} / 稳 {result.get('稳_count', 0)} / 保 {result.get('保_count', 0)}。\n"
        f"风险提示：{'; '.join(result.get('warnings', [])) if result.get('warnings') else '无'}"
    )
    return chat_completion(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.5,
        max_tokens=256,
    )
