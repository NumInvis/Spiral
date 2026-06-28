import json
import os
from typing import Dict, List, Optional

_RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "province_rules")

# 当前志愿填报年份（用于 cutoff、招生计划、Agent 默认检索等）
CURRENT_YEAR = 2026
# 已有完整录取数据的最新年份（2026 年录取尚未结束，因此最新为 2025）
LATEST_HISTORICAL_YEAR = 2025
# 推荐系统默认读取的招生计划年份
DEFAULT_PLAN_YEAR = CURRENT_YEAR


def _load_rules() -> Dict[str, Dict]:
    rules = {}
    if not os.path.isdir(_RULES_DIR):
        return rules
    for fname in sorted(os.listdir(_RULES_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_RULES_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            province = data.get("province")
            if province:
                rules[province] = data
        except Exception as e:
            print(f"[province_rules] failed to load {fname}: {e}")
    return rules


PROVINCE_RULES: Dict[str, Dict] = _load_rules()


def list_provinces() -> List[Dict]:
    return [
        {"province": p, "code": r.get("province_code"), "enabled": r.get("enabled", True)}
        for p, r in PROVINCE_RULES.items()
    ]


def get_province_rule(province: str) -> Optional[Dict]:
    return PROVINCE_RULES.get(province)


def default_rule() -> Dict:
    return PROVINCE_RULES.get("湖北", {})
