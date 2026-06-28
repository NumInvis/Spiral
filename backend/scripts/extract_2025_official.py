"""Extract 2025 Hubei本科普通批院校专业组投档线 + 一分一段表 from official PDFs.

Inputs (place in gaokao-agent/.tmp_data/):
    - 2025_physics.pdf  : 湖北省2025年本科普通批录取院校（首选物理）平行志愿投档分数线
    - 2025_history.pdf  : 湖北省2025年本科普通批录取院校（首选历史）平行志愿投档分数线
    - 2025_rank_physics.pdf / 2025_rank_history.pdf : 湖北省2025年普通高考总分一分一段统计表

Outputs (in gaokao-agent/.tmp_data/):
    - 2025_group_scores.csv   : 科类,专业组代码,专业组名称,投档最低分_2025,备注
    - 2025_score_rank.csv     : 科类,分数,累计人数（位次）
    - 2025_group_ranks.csv    : 科类,专业组代码,专业组名称,投档最低分_2025,投档最低位次_2025,备注
"""

import re
import csv
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp_data"
OUT = TMP


def clean(cell, aggressive=False):
    if cell is None:
        return ""
    s = str(cell)
    s = re.sub(r"[\n\r\t]+", "", s)
    s = s.replace(" ", "")
    if aggressive:
        # Drop watermark phrases that leak into numeric cells
        for frag in (
            "湖北省教育厅",
            "湖北招生",
            "省招办",
            "招生信息",
            "微信公众号",
            "www",
            "http",
            "https",
            "com",
            "cn",
            "gov",
            "e21",
            "hbksw",
            "jyt",
            "edu",
        ):
            s = s.replace(frag, "")
        # Remove stray CJK characters and letters that remain in numeric cells
        s = re.sub(r"[a-zA-Z]+", "", s)
        s = re.sub(r"[\u4e00-\u9fa5]+", "", s)
    return s.strip()


def extract_digits(cell):
    """Extract only digits from a cell; useful when watermark text contaminates numbers."""
    if cell is None:
        return ""
    s = re.sub(r"[\n\r\t ]+", "", str(cell))
    for frag in (
        "湖北省教育厅",
        "湖北招生",
        "省招办",
        "招生信息",
        "微信公众号",
        "www",
        "http",
        "https",
    ):
        s = s.replace(frag, "")
    s = re.sub(r"[a-zA-Z\u4e00-\u9fa5]+", "", s)
    return s.strip()


SPECIAL_TYPE_KEYWORDS = [
    "国家专项计划",
    "地方专项计划",
    "少数民族预科班",
    "边防子女预科班",
    "中外合作办学",
    "定向就业",
    "民族班",
    "预科班",
    "护理类",
    "高收费",
    "国家优师专项",
    "地方优师专项",
    "楚怡工匠计划",
]


def _sanitize_note(note: str) -> str:
    if not note:
        return ""
    # Keep if it contains a known special-type keyword
    for kw in SPECIAL_TYPE_KEYWORDS:
        if kw in note:
            return kw
    # Otherwise keep only if it has at least 4 CJK characters (avoids watermark fragments)
    cjk = re.findall(r"[\u4e00-\u9fa5]", note)
    if len(cjk) >= 4:
        return note
    return ""


REQ_SUBJECTS = set("化学生地政")


def _clean_req(cell) -> str:
    """Normalize '再选科目要求' to the same style used in the 2024 CSV."""
    if cell is None:
        return "不限"
    s = str(cell).replace("\n", "").strip()
    # Remove common watermark prefixes / stray chars
    s = re.sub(r"^(省|厅|北|号|信|微|【|】)+", "", s)
    # Keep only subject chars and connectors
    s = re.sub(r"[^化学生地政或和]", "", s)
    if not s or "不限" in s:
        return "不限"
    parts = re.split(r"[或和]", s)
    chars = sorted({p for p in parts if p in REQ_SUBJECTS})
    return "与".join(chars) if chars else "不限"


def extract_group_lines(pdf_path: Path, subject: str):
    """Return list of dicts for each 院校专业组 row."""
    rows = []
    code_pat = re.compile(r"^[A-Z]\d{5}$")
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                # Skip header / sub-header rows
                for raw in table[2:]:
                    if not raw or not any(raw):
                        continue
                    cells = [clean(c) for c in raw]
                    # Locate group code cell
                    code_idx = None
                    for i, c in enumerate(cells):
                        if code_pat.match(c):
                            code_idx = i
                            break
                    if code_idx is None:
                        continue
                    code = cells[code_idx]
                    # Group name is next non-empty cell containing 第X组
                    name = ""
                    for c in cells[code_idx + 1 :]:
                        if "第" in c and "组" in c:
                            name = c
                            break
                    if not name:
                        # fallback: next non-empty
                        for c in cells[code_idx + 1 :]:
                            if c:
                                name = c
                                break
                    # Score: first cell after code/name whose digits form a plausible score (100-800)
                    score = ""
                    score_idx = None
                    req = ""
                    for i, c in enumerate(cells[code_idx + 1 :], start=code_idx + 1):
                        digits = extract_digits(raw[i])
                        if re.fullmatch(r"\d{3}", digits) and 100 <= int(digits) <= 800:
                            score = digits
                            score_idx = i
                            # The cell immediately before the score is the requirement column
                            req = raw[i - 1] if i - 1 >= code_idx + 1 else ""
                            break
                    if not score:
                        continue
                    req = _clean_req(req)
                    # Note: any non-numeric text after score, excluding tie-breaker columns
                    note_parts = []
                    for c in raw[score_idx + 1 :] if score_idx else []:
                        txt = str(c).replace("\n", "").strip() if c is not None else ""
                        if not txt:
                            continue
                        if re.fullmatch(r"\d+", txt):
                            continue
                        note_parts.append(txt)
                    note = "、".join(note_parts).strip("、")
                    note = re.sub(r"[\s、]+", "、", note).strip("、")
                    note = _sanitize_note(note)
                    rows.append(
                        {
                            "科类": subject,
                            "专业组代码": code,
                            "专业组名称": name,
                            "选科限制": req,
                            "投档最低分_2025": int(score),
                            "备注": note,
                        }
                    )
    return rows


def extract_rank_counts(pdf_path: Path, subject: str):
    """Extract (score, count) pairs from one-point-one-segment PDF.

    The rightmost cumulative column often contains watermark text, so we ignore it
    and recompute cumulative ranks ourselves from the clean (score, count) pairs.
    """
    pairs = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for raw in table:
                    cells = [clean(c, aggressive=True) for c in raw]
                    if not cells or not cells[0]:
                        continue
                    # Skip header rows
                    if any(h in str(c) for c in raw[:2] for h in ("分数", "人数", "累计人数")):
                        continue
                    # Process in triplets; accept if score and count are numeric
                    for i in range(0, len(cells) - 1, 3):
                        score, count = cells[i], cells[i + 1]
                        if re.fullmatch(r"\d+", score) and re.fullmatch(r"\d+", count):
                            pairs.append((int(score), int(count)))
    # Deduplicate, keep max count if a score appears multiple times
    count_map = {}
    for s, c in pairs:
        count_map[s] = max(count_map.get(s, 0), c)
    # Sort descending by score and compute cumulative rank
    rows = []
    cumulative = 0
    for s in sorted(count_map.keys(), reverse=True):
        cumulative += count_map[s]
        rows.append({"科类": subject, "分数": s, "累计人数": cumulative, "人数": count_map[s]})
    return rows


def main():
    files = {
        "物理": (TMP / "2025_physics.pdf", TMP / "2025_rank_physics.pdf"),
        "历史": (TMP / "2025_history.pdf", TMP / "2025_rank_history.pdf"),
    }
    all_groups = []
    all_ranks = []
    for subject, (score_pdf, rank_pdf) in files.items():
        if not score_pdf.exists():
            print(f"SKIP {subject}: {score_pdf} not found", file=sys.stderr)
            continue
        print(f"Extracting {subject} group scores ...")
        groups = extract_group_lines(score_pdf, subject)
        print(f"  -> {len(groups)} groups")
        all_groups.extend(groups)

        print(f"Extracting {subject} rank table ...")
        rank_rows = extract_rank_counts(rank_pdf, subject)
        print(f"  -> {len(rank_rows)} score points")
        all_ranks.extend(rank_rows)

    # Save group scores
    score_csv = OUT / "2025_group_scores.csv"
    with score_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["科类", "专业组代码", "专业组名称", "选科限制", "投档最低分_2025", "备注"]
        )
        writer.writeheader()
        writer.writerows(all_groups)
    print(f"Wrote {score_csv}")

    # Save rank table
    rank_csv = OUT / "2025_score_rank.csv"
    with rank_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["科类", "分数", "人数", "累计人数"])
        writer.writeheader()
        writer.writerows(all_ranks)
    print(f"Wrote {rank_csv}")

    # Build dense rank lookup: for any score, return cumulative rank at that score,
    # or at the next higher score if the exact score has zero candidates.
    rank_map = {}
    for subject in ("物理", "历史"):
        rows_sub = [r for r in all_ranks if r["科类"] == subject]
        if not rows_sub:
            continue
        rows_sub.sort(key=lambda x: x["分数"], reverse=True)
        max_score = rows_sub[0]["分数"]
        min_score = rows_sub[-1]["分数"]
        # Sort ascending to fill gaps
        ascending = sorted(rows_sub, key=lambda x: x["分数"])
        # cumulative rank for a score = sum of counts for scores >= that score
        # We have cumulative in rows_sub, use it.
        asc_iter = iter(ascending)
        cur = next(asc_iter)
        for s in range(min_score, max_score + 1):
            if s == cur["分数"]:
                rank_map[(subject, s)] = cur["累计人数"]
                cur = next(asc_iter, None)
                if cur is None:
                    break
            elif s < cur["分数"]:
                # gap: use cumulative rank of next higher known score
                rank_map[(subject, s)] = cur["累计人数"]
        # Above max score -> top rank (same as max score)
        top_rank = rows_sub[0]["累计人数"]
        rank_map[(subject, max_score + 1)] = top_rank

    merged = []
    missing = 0
    for g in all_groups:
        score = g["投档最低分_2025"]
        rank = rank_map.get((g["科类"], score))
        if rank is None:
            missing += 1
            rank = ""
        merged.append(
            {
                "科类": g["科类"],
                "专业组代码": g["专业组代码"],
                "专业组名称": g["专业组名称"],
                "选科限制": g.get("选科限制", ""),
                "投档最低分_2025": score,
                "投档最低位次_2025": rank,
                "备注": g["备注"],
            }
        )
    if missing:
        print(f"WARNING: {missing} groups could not be mapped to rank", file=sys.stderr)

    group_rank_csv = OUT / "2025_group_ranks.csv"
    with group_rank_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "科类",
                "专业组代码",
                "专业组名称",
                "选科限制",
                "投档最低分_2025",
                "投档最低位次_2025",
                "备注",
            ],
        )
        writer.writeheader()
        writer.writerows(merged)
    print(f"Wrote {group_rank_csv}")


if __name__ == "__main__":
    main()
