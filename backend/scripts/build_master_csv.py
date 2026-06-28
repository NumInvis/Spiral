"""Merge 2025 official group-level ranks into the existing 2024 CSV.

Matching strategy:
1. Direct full group code match where 2024/2025 codes are identical.
2. Otherwise fall back to base school code + subject + requirement, pairing groups
   with the closest historical ranks to minimize misalignment.

Produces backend/data/raw_hubei_2024_2025.csv.
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backend" / "data"
TMP_DIR = ROOT / ".tmp_data"


def _base_code(full_code: str) -> str:
    return full_code[:-2] if len(full_code) >= 3 else full_code


def _parse_rank(value):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _stable_match(df24_groups, df25_groups, key_cols, rank_col24, rank_col25):
    """Return dict mapping 2024 full code -> 2025 row for groups matched by key_cols."""
    mapping = {}
    used25 = set()

    # First pass: exact key match (base + subject + requirement)
    g24 = df24_groups.groupby(key_cols, sort=False)
    g25 = df25_groups.groupby(key_cols, sort=False)
    for key, sub24 in g24:
        if key not in g25.groups:
            continue
        sub25 = df25_groups.loc[g25.groups[key]].copy()
        sub24 = sub24.sort_values(rank_col24, ascending=True)
        sub25 = sub25.sort_values(rank_col25, ascending=True)
        for (_, r24), (_, r25) in zip(sub24.iterrows(), sub25.iterrows()):
            code24 = r24["院校代码"]
            if code24 in mapping:
                continue
            code25 = r25["专业组代码"]
            if code25 in used25:
                continue
            mapping[code24] = r25
            used25.add(code25)

    return mapping, used25


def main():
    csv_2024 = DATA_DIR / "raw_hubei_2024.csv"
    csv_2025 = TMP_DIR / "2025_group_ranks.csv"
    out = DATA_DIR / "raw_hubei_2024_2025.csv"

    df = pd.read_csv(csv_2024, low_memory=False, dtype=str)
    df25 = pd.read_csv(csv_2025, low_memory=False, dtype=str)

    df["_rank24"] = df["专业组最低位次"].apply(_parse_rank)
    df25["_rank25"] = df25["投档最低位次_2025"].apply(_parse_rank)
    df["_base"] = df["院校代码"].apply(_base_code)
    df25["_base"] = df25["专业组代码"].apply(_base_code)

    # Build 2024 group-level view
    group24 = (
        df.groupby(["院校代码", "科类"], sort=False)
        .agg(
            {
                "_rank24": "first",
                "_base": "first",
                "选科限制": "first",
                "院校名称": "first",
            }
        )
        .reset_index()
    )
    group24 = group24[group24["_rank24"].notna()].copy()

    # Build 2025 group-level view
    group25 = df25[["专业组代码", "科类", "选科限制", "投档最低分_2025", "投档最低位次_2025", "备注", "_rank25", "_base"]].copy()

    # Pass 1: exact full code match
    direct = {}
    used25 = set()
    for _, r24 in group24.iterrows():
        mask = (group25["专业组代码"] == r24["院校代码"]) & (group25["科类"] == r24["科类"])
        cand = group25[mask]
        if len(cand) == 1:
            code24 = r24["院校代码"]
            direct[code24] = cand.iloc[0]
            used25.add(cand.iloc[0]["专业组代码"])

    # Pass 2: base + subject + requirement, stable rank-ordered match
    key_cols = ["_base", "科类", "选科限制"]
    remaining24 = group24[~group24["院校代码"].isin(direct.keys())].copy()
    remaining25 = group25[~group25["专业组代码"].isin(used25)].copy()
    matched2, used25_2 = _stable_match(remaining24, remaining25, key_cols, "_rank24", "_rank25")
    direct.update(matched2)
    used25 |= used25_2

    # Pass 3: base + subject only (ignore requirement drift), stable rank-ordered match
    remaining24 = group24[~group24["院校代码"].isin(direct.keys())].copy()
    remaining25 = group25[~group25["专业组代码"].isin(used25)].copy()
    key_cols2 = ["_base", "科类"]
    matched3, _ = _stable_match(remaining24, remaining25, key_cols2, "_rank24", "_rank25")
    direct.update(matched3)

    # Build merge columns on df using the mapping
    def map25(code, subject, col):
        r = direct.get(code)
        if r is None:
            return None
        # r may be a Series; ensure right column
        if col == "专业组代码_2025":
            return r["专业组代码"]
        return r.get(col)

    df["专业组代码_2025"] = df.apply(
        lambda r: map25(r["院校代码"], r["科类"], "专业组代码_2025"), axis=1
    )
    df["专业组最低分_2025"] = df.apply(
        lambda r: map25(r["院校代码"], r["科类"], "投档最低分_2025"), axis=1
    )
    df["专业组最低位次_2025"] = df.apply(
        lambda r: map25(r["院校代码"], r["科类"], "投档最低位次_2025"), axis=1
    )
    df["专业组备注_2025"] = df.apply(
        lambda r: map25(r["院校代码"], r["科类"], "备注"), axis=1
    )

    # Drop helper columns
    df = df.drop(columns=["_rank24", "_base"])

    # Keep rows even if 2025 mapping is missing; they will fall back to 2024 data.
    df.to_csv(out, index=False, encoding="utf-8-sig")
    matched = df["专业组最低位次_2025"].notna().sum()
    print(f"Wrote {out}")
    print(f"  total rows: {len(df)}")
    print(f"  rows with 2025 mapping: {matched}")
    print(f"  rows with only 2024 data: {len(df) - matched}")
    print(f"  distinct 2025 groups matched: {df['专业组代码_2025'].nunique()}")


if __name__ == "__main__":
    main()
