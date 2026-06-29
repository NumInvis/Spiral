import os
import re
import json
import urllib.request
from typing import Optional, Dict, List, Iterable, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from models import School, Major, MajorScore, AdmissionPlan, RankTable
from config.province_rules import CURRENT_YEAR, LATEST_HISTORICAL_YEAR


_EXTERNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".tmp_data", "external")
_HUBEI_SQL_URL = "https://raw.githubusercontent.com/Jsoneft/gaokao-zhiyuan/main/hubei_data/insert_data_fixed.sql"


def _external_path(filename: str) -> str:
    os.makedirs(_EXTERNAL_DIR, exist_ok=True)
    return os.path.abspath(os.path.join(_EXTERNAL_DIR, filename))


def _download_file(url: str, dest: str, timeout: int = 120) -> str:
    if not os.path.exists(dest):
        print(f"[download] {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)
    return dest


def _parse_int(value, default=None):
    if value is None or pd.isna(value):
        return default
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _parse_float(value, default=None):
    if value is None or pd.isna(value):
        return default
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _infer_level(tags: str, level_text: str) -> str:
    tags = tags or ""
    level_text = level_text or ""
    combined = tags + level_text
    if "985" in combined:
        return "985"
    if "211" in combined and "985" not in combined:
        return "211"
    if "双一流" in combined:
        return "双一流"
    if "民办" in level_text or "民办" in tags:
        return "民办本科"
    return "普通本科"


def _has_tag(tags: str, keyword: str) -> bool:
    return keyword in (tags or "")


def _clean_city(city: str) -> str:
    if not city:
        return ""
    city = str(city).strip()
    for prefix in ["湖北", "湖南", "安徽", "江西", "北京", "上海", "天津", "重庆"]:
        if city.startswith(prefix):
            rest = city[len(prefix):]
            rest = re.sub(r"^(省|市)", "", rest)
            if rest:
                return rest
    return city


def _iter_sql_tuples(block: str) -> Iterable[str]:
    """从 SQL VALUES 块中安全地切分出每一行元组（处理字符串内括号/逗号）。"""
    buf = []
    depth = 0
    in_str = False
    escape = False
    i = 0
    while i < len(block):
        ch = block[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_str = False
            buf.append(ch)
        else:
            if ch == "'":
                in_str = True
                buf.append(ch)
            elif ch == "(":
                if depth == 0:
                    buf = []
                depth += 1
                buf.append(ch)
            elif ch == ")":
                depth -= 1
                buf.append(ch)
                if depth == 0:
                    yield "".join(buf).strip()
                    buf = []
            elif ch == ";":
                if depth == 0:
                    pass
                else:
                    buf.append(ch)
            else:
                if depth > 0:
                    buf.append(ch)
        i += 1


def _parse_sql_row(tuple_str: str) -> List:
    """把单个 VALUES 元组解析成 Python 值列表。"""
    body = tuple_str.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    # SQL: false/true/NULL; Python 需要 False/True/None
    body = body.replace("NULL", "None").replace("true", "True").replace("false", "False")
    # SQL 字符串转义使用 '' -> '
    body = re.sub(r"(?<!\\)''", r"\\'", body)
    try:
        return list(ast.literal_eval(f"[{body}]"))
    except Exception:
        return []


import ast  # noqa: E402


def _load_major_descriptions_from_sql(sql_path: Optional[str] = None) -> Dict[Tuple[str, str, str, str], str]:
    """从 gaokao-zhiyuan SQL dump 中读取每个专业的官方招生说明。

    返回: {(院校代码, 专业组代码, 专业代码, 科类): description}
    """
    if sql_path is None:
        sql_path = _external_path("hubei_insert_data_fixed.sql")
        sql_path = _download_file(_HUBEI_SQL_URL, sql_path)

    if not os.path.exists(sql_path):
        return {}

    desc_map: Dict[Tuple[str, str, str, str], str] = {}
    with open(sql_path, "r", encoding="utf-8") as f:
        in_values = False
        buffer = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            if "VALUES" in line.upper():
                in_values = True
                # 本行可能在 VALUES 后已有内容
                idx = line.upper().find("VALUES")
                buffer.append(line[idx + len("VALUES"):])
                continue
            if not in_values:
                continue
            buffer.append(line)
            if line.endswith(";"):
                block = "\n".join(buffer)
                buffer = []
                in_values = False
                for tup in _iter_sql_tuples(block):
                    vals = _parse_sql_row(tup)
                    if len(vals) < 31:
                        continue
                    # 列序号按 gaokao-zhiyuan admission_hubei_wide_2024 表结构
                    school_code = str(vals[1]) if vals[1] else ""
                    major_code = str(vals[3]) if vals[3] else ""
                    major_group_code = str(vals[5]) if vals[5] else ""
                    subject_category = str(vals[10]) if vals[10] else ""
                    description = str(vals[24]) if vals[24] else ""
                    if description and description.lower() != "none":
                        key = (school_code, major_group_code, major_code, subject_category)
                        desc_map[key] = description
    print(f"[sql] loaded {len(desc_map)} major descriptions from {sql_path}")
    return desc_map


def import_ranking_json(
    db: Session,
    json_path: str,
    province: str,
    subject_type: str,
    year: int,
    source: Optional[str] = None,
) -> dict:
    """导入一分一段表 JSON（FlySky-z/gaokao-analysis 格式）。"""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Ranking JSON not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload

    # 清除旧数据
    db.query(RankTable).filter(
        RankTable.province == province,
        RankTable.subject_type == subject_type,
        RankTable.year == year,
    ).delete(synchronize_session=False)

    inserted = 0
    for r in rows:
        score_raw = str(r.get("score", "")).strip()
        num = _parse_int(r.get("num"), 0)
        acc = _parse_int(r.get("accumulate"))
        if not score_raw or acc is None:
            continue
        # score 可能是 "695-750" 区间
        if "-" in score_raw:
            try:
                lo, hi = score_raw.split("-", 1)
                lo, hi = int(lo), int(hi)
            except Exception:
                continue
            scores = list(range(lo, hi + 1))
        else:
            s = _parse_int(score_raw)
            if s is None:
                continue
            scores = [s]
        for sc in scores:
            db.add(RankTable(
                province=province,
                subject_type=subject_type,
                year=year,
                score=sc,
                num=num,
                accumulate=acc,
                source=source or f"{province}{year}年一分一段表",
            ))
            inserted += 1
    db.commit()
    return {"province": province, "subject_type": subject_type, "year": year, "rows": inserted}


def import_ranking_csv(
    db: Session,
    csv_path: str,
    province: str,
    subject_type: str,
    year: int,
    source: Optional[str] = None,
) -> dict:
    """导入一分一段表 CSV（官方 PDF 提取格式：科类,分数,人数,累计人数）。"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Ranking CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    # 过滤出对应科类
    rows = df[df["科类"] == subject_type]

    db.query(RankTable).filter(
        RankTable.province == province,
        RankTable.subject_type == subject_type,
        RankTable.year == year,
    ).delete(synchronize_session=False)

    inserted = 0
    for _, r in rows.iterrows():
        score = _parse_int(r.get("分数"))
        num = _parse_int(r.get("人数"), 0)
        acc = _parse_int(r.get("累计人数"))
        if score is None or acc is None:
            continue
        db.add(RankTable(
            province=province,
            subject_type=subject_type,
            year=year,
            score=score,
            num=num,
            accumulate=acc,
            source=source or f"{province}{year}年官方一分一段表",
        ))
        inserted += 1
    db.commit()
    return {"province": province, "subject_type": subject_type, "year": year, "rows": inserted}


def score_to_rank(
    db: Session,
    province: str,
    subject_type: str,
    year: int,
    score: int,
) -> Optional[int]:
    """根据一分一段表把分数换算为位次；无精确匹配时线性插值。"""
    row = db.query(RankTable).filter(
        RankTable.province == province,
        RankTable.subject_type == subject_type,
        RankTable.year == year,
        RankTable.score == score,
    ).first()
    if row and row.accumulate is not None:
        return row.accumulate
    # 插值：取相邻两个分数点
    lower = db.query(RankTable).filter(
        RankTable.province == province,
        RankTable.subject_type == subject_type,
        RankTable.year == year,
        RankTable.score < score,
    ).order_by(RankTable.score.desc()).first()
    upper = db.query(RankTable).filter(
        RankTable.province == province,
        RankTable.subject_type == subject_type,
        RankTable.year == year,
        RankTable.score > score,
    ).order_by(RankTable.score.asc()).first()
    if lower and upper and lower.accumulate is not None and upper.accumulate is not None:
        if lower.score == upper.score:
            return lower.accumulate
        ratio = (score - lower.score) / (upper.score - lower.score)
        return int(lower.accumulate + ratio * (upper.accumulate - lower.accumulate))
    if lower and lower.accumulate is not None:
        return lower.accumulate
    if upper and upper.accumulate is not None:
        return upper.accumulate
    return None


def import_hubei_csv(
    db: Session,
    csv_path: Optional[str] = None,
    clear: bool = True,
    plan_year: int = LATEST_HISTORICAL_YEAR,
    enrich_descriptions: bool = True,
) -> dict:
    """从 gaokao-zhiyuan 开源整理的湖北投档/计划 CSV 导入真实数据。

    CSV 中列含义（按当前数据集约定）：
    - 计划数：当前志愿填报年份的招生计划（默认记为 CURRENT_YEAR）
    - 专业组最低分/位次：最近一年完整投档数据（2024）
    - 专业组最低分.1/位次.1：上一年完整投档数据（2023）
    """
    if csv_path is None:
        csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "raw_hubei_2024.csv")
    csv_path = os.path.abspath(csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # 预加载官方 SQL 中的专业说明
    desc_map = _load_major_descriptions_from_sql() if enrich_descriptions else {}

    df = pd.read_csv(csv_path, low_memory=False, dtype=str)
    # 仅保留本科普通批本科层次
    if "批次" in df.columns:
        df = df[df["批次"].fillna("").str.contains("本科批")]
    if "本科/专科" in df.columns:
        df = df[df["本科/专科"].fillna("") == "本科"]

    if clear:
        db.query(MajorScore).delete(synchronize_session=False)
        db.query(AdmissionPlan).delete(synchronize_session=False)
        db.query(Major).delete(synchronize_session=False)
        db.query(School).delete(synchronize_session=False)
        db.commit()

    school_cache = {}
    major_cache = {}
    stats = {"schools": 0, "majors": 0}

    for _, row in df.iterrows():
        raw_code = str(row.get("院校代码", "")).strip()
        if len(raw_code) < 3:
            continue
        school_code = raw_code[:-2] if len(raw_code) >= 2 else raw_code
        group_code = raw_code[-2:]
        subject_type = str(row.get("科类", "")).strip()
        if subject_type not in ("物理", "历史"):
            continue

        # School
        if school_code not in school_cache:
            school_name = str(row.get("院校名称", "")).strip()
            tags = str(row.get("院校标签", "")).strip()
            level_text = str(row.get("院校水平", "")).strip()
            ownership = str(row.get("公私性质", "")).strip()
            school = School(
                code=school_code,
                name=school_name,
                level=_infer_level(tags, level_text),
                province=str(row.get("所在省", "")).strip() or None,
                city=_clean_city(str(row.get("城市", "")).strip()) or None,
                is_public=(ownership != "民办"),
                has_master=_has_tag(tags, "保研") or _has_tag(tags, "研究生院"),
                has_phd=_has_tag(tags, "研究生院") or _has_tag(level_text, "博士"),
                category=str(row.get("类型", "")).strip() or None,
                tags=tags,
            )
            db.add(school)
            db.flush()
            school_cache[school_code] = school
            stats["schools"] += 1
        else:
            school = school_cache[school_code]

        # Major
        major_code = str(row.get("专业代码", "")).strip()
        major_name = str(row.get("专业名称", "")).strip()
        cache_key = (school.id, group_code, major_code, subject_type)
        if cache_key not in major_cache:
            require = str(row.get("选科限制", "")).strip() or "不限"
            duration = _parse_int(row.get("学制"), 4)
            tuition = _parse_int(row.get("学费"))
            # 尝试从 SQL 说明中补全专业介绍
            desc_key = (raw_code, group_code.lstrip("0") or "0", major_code, subject_type)
            description = desc_map.get(desc_key)
            if not description:
                # 兼容：group_code 不带前导零
                desc_key2 = (raw_code, str(int(group_code)) if group_code.isdigit() else group_code, major_code, subject_type)
                description = desc_map.get(desc_key2)
            # 合并 CSV 中的专业备注（含中外合作办学/国家专项/民族班等标记）
            csv_note = str(row.get("专业备注", "")).strip()
            if csv_note and csv_note.lower() not in ("nan", "none", ""):
                if description:
                    description = f"{csv_note}\n{description}"
                else:
                    description = csv_note
            major = Major(
                school_id=school.id,
                code=major_code,
                name=major_name,
                group_code=group_code,
                category=_infer_major_category(row),
                subject_require=require,
                duration=duration,
                tuition=tuition,
                discipline_eval=None,
                employment_score=0.0,
                description=description,
            )
            db.add(major)
            db.flush()
            major_cache[cache_key] = major
            stats["majors"] += 1
        else:
            major = major_cache[cache_key]

        # 投档数据：区分专业真实线（A）与专业组投档线（B/C）。
        # 2024/2023/2022 来自开源整理的官方投档/录取数据；2025 来自湖北省教育考试院官方 PDF。
        raw_group_code = str(row.get("专业组代码", "")).strip() or None
        group_code_2025 = str(row.get("专业组代码_2025", "")).strip() or None
        score_spec = [
            # (year, major_score_col, major_rank_col, group_score_col, group_rank_col,
            #  confidence_if_major, confidence_if_group, group_code_source)
            (2024, "最低分", "最低位次", "专业组最低分", "专业组最低位次", "A", "B", raw_group_code),
            (2023, "最低分.1", "最低位次.1", "专业组最低分.1", "专业组最低位次.1", "A", "B", raw_group_code),
            (2022, "最低分.2", "最低位次.2", None, None, "A", None, raw_group_code),
            (2025, None, None, "专业组最低分_2025", "专业组最低位次_2025", None, "C", group_code_2025),
        ]
        for year, major_score_col, major_rank_col, group_score_col, group_rank_col, conf_major, conf_group, gc_src in score_spec:
            major_s = _parse_int(row.get(major_score_col)) if major_score_col else None
            major_r = _parse_int(row.get(major_rank_col)) if major_rank_col else None
            group_s = _parse_int(row.get(group_score_col)) if group_score_col else None
            group_r = _parse_int(row.get(group_rank_col)) if group_rank_col else None

            if (major_s is None and major_r is None and group_s is None and group_r is None):
                continue

            # 优先使用专业真实线；否则退回到组线，且不做热度估算
            if major_r is not None:
                best_s, best_r, confidence = major_s, major_r, conf_major
            elif group_r is not None:
                best_s, best_r, confidence = group_s, group_r, conf_group
            else:
                # 有位次缺失但分数存在的情况：仅用分数，置信度取组线
                best_s, best_r, confidence = major_s or group_s, None, conf_group or conf_major or "C"

            if year == 2025:
                source = "湖北省教育考试院2025年本科普通批院校专业组投档线（PDF）"
                # 追加组级别备注（国家专项/民族班/中外合作等），用于特殊类型识别
                note_2025 = str(row.get("专业组备注_2025", "")).strip()
                if note_2025 and note_2025.lower() not in ("nan", "none", ""):
                    source = f"{source} | {note_2025}"
            elif major_r is not None:
                source = f"湖北{year}年本科普通批专业录取数据"
            else:
                source = f"湖北{year}年本科普通批院校专业组投档线"

            # 该年份对应的组代码：2025 用官方 PDF 组代码，其它年份用 CSV 原始组代码
            if gc_src:
                gc = gc_src[-2:] if len(gc_src) >= 2 and gc_src[0].isalpha() else gc_src
            else:
                gc = None

            db.add(MajorScore(
                major_id=major.id,
                province="湖北",
                subject_type=subject_type,
                year=year,
                lowest_score=best_s,
                lowest_rank=best_r,
                group_lowest_score=group_s,
                group_lowest_rank=group_r,
                group_code=gc,
                data_confidence=confidence,
                data_source=source,
            ))
            stats[f"scores_{year}"] = stats.get(f"scores_{year}", 0) + 1

        # 当前年份招生计划
        plan = _parse_int(row.get("计划数"), 0)
        if plan is not None and plan > 0:
            db.add(AdmissionPlan(
                major_id=major.id,
                province="湖北",
                subject_type=subject_type,
                year=plan_year,
                plan_count=plan,
                group_code=group_code,
            ))
            stats[f"plans_{plan_year}"] = stats.get(f"plans_{plan_year}", 0) + 1

    db.commit()
    return stats


def _infer_major_category(row) -> Optional[str]:
    if _bool(row.get("工科")):
        return "工科"
    if _bool(row.get("理科")):
        return "理科"
    if _bool(row.get("医科")):
        return "医科"
    if _bool(row.get("经管法")):
        return "经管"
    if _bool(row.get("文科（非经管法）")):
        return "文科"
    if _bool(row.get("设计与艺术类")):
        return "艺术"
    if _bool(row.get("语言类")):
        return "文科"
    return None


def _bool(value) -> bool:
    if value is None or pd.isna(value):
        return False
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "是")
