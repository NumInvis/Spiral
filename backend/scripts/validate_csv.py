"""
Spiral Data Validator — 数据真实性校验与血缘追踪系统

核心功能：
1. 官方数据交叉验证（CSV vs 教育考试院官方 PDF）
2. 专业线 >= 组线一致性校验
3. 异常值检测（分数跳跃、位次突变等）
4. 数据血缘追踪标记生成
5. 可操作的修正建议报告

用法：
    python validate_csv.py \
        --csv backend/data/raw_hubei_2024_2025.csv \
        --official data_pipeline/official/hubei_2024_physics_official.txt \
        --output data_pipeline/reports/validation_report.json

作者: Spiral Dev Team
"""
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class ValidationIssue:
    severity: str          # ERROR / WARN / INFO
    category: str          # official_mismatch / group_major_inversion / missing_major_score / suspicious_rank / etc
    key: str               # 院校代码+组号 或 记录ID
    field: str             # 出问题的字段
    expected: Optional[str]  # 期望值
    actual: Optional[str]  # 实际值
    suggestion: str        # 修正建议
    confidence_before: str # 修正前的置信度
    confidence_after: str  # 修正后的置信度


@dataclass
class DataLineage:
    """单条数据记录的血缘追踪信息"""
    source_type: str         # official_pdf / third_party_crawl / unknown
    source_url: str
    source_file: str
    fetched_at: str          # ISO 8601
    validated_at: str
    validator_version: str
    cross_check_passed: bool
    issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 官方数据解析器
# ---------------------------------------------------------------------------
def parse_official_text(path: str) -> Dict[str, dict]:
    """解析从教育考试院 PDF 提取的文本，返回 {完整代码: {school_name, score}}"""
    records = {}
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines[2:]:
        line = line.strip()
        if not line or line.startswith("第") or line.startswith("<footer>"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        try:
            group_code_full = parts[0].strip()
            school_group = parts[1].strip()
            subject_req = parts[2].strip()
            score = parts[3].strip()
            if not group_code_full or not score.isdigit():
                continue
            m = re.match(r"(.+?)第(\d+)组", school_group)
            school_name = m.group(1) if m else school_group
            records[group_code_full] = {
                "school_name": school_name,
                "subject_require": subject_req,
                "score_2024_official": int(score),
            }
        except Exception:
            continue
    return records


# ---------------------------------------------------------------------------
# CSV 加载器
# ---------------------------------------------------------------------------
def load_csv_groups(csv_path: str, subject_type: str = "物理") -> Dict[str, dict]:
    """从 CSV 加载指定科类的唯一组线数据，返回 {完整代码: {csv_score, school_name, ...}}"""
    df = pd.read_csv(csv_path, low_memory=False, dtype=str)
    df_sub = df[df["科类"] == subject_type].copy()

    groups = {}
    for _, row in df_sub.iterrows():
        raw_code = str(row.get("院校代码", "")).strip()
        score = str(row.get("专业组最低分", "")).strip()
        if not raw_code or not score:
            continue
        try:
            score_f = float(score)
        except ValueError:
            continue
        if raw_code not in groups:
            groups[raw_code] = {
                "csv_score_2024": score_f,
                "school_name_csv": str(row.get("院校名称", "")).strip(),
                "group_code": str(row.get("专业组代码", "")).strip(),
                "subject_require": str(row.get("选科限制", "")).strip() or "不限",
            }
    return groups


# ---------------------------------------------------------------------------
# 校验器核心
# ---------------------------------------------------------------------------
class DataValidator:
    def __init__(self, csv_path: str, official_path: Optional[str] = None):
        self.csv_path = csv_path
        self.official_path = official_path
        self.issues: List[ValidationIssue] = []
        self.lineage: Dict[str, DataLineage] = {}

    def run(self) -> dict:
        """执行全量校验，返回报告"""
        # 1. 官方交叉验证
        if self.official_path and os.path.exists(self.official_path):
            self._cross_validate_official()

        # 2. 组线 vs 专业线一致性
        self._validate_group_major_consistency()

        # 3. 异常值检测
        self._detect_outliers()

        # 4. 生成血缘标记
        self._build_lineage()

        return self._build_report()

    # -----------------------------------------------------------------------
    # 1. 官方交叉验证
    # -----------------------------------------------------------------------
    def _cross_validate_official(self):
        official = parse_official_text(self.official_path)
        csv_groups = load_csv_groups(self.csv_path, "物理")

        for key, rec in official.items():
            lineage = DataLineage(
                source_type="official_pdf",
                source_url="http://jyt.hubei.gov.cn/bmdt/ztzl/gxzs/zszy/zsfw/202407/t20240721_5274253.shtml",
                source_file=os.path.basename(self.official_path),
                fetched_at="2025-06-29",
                validated_at="2025-06-29",
                validator_version="1.0.0",
                cross_check_passed=True,
            )
            if key in csv_groups:
                csv_score = csv_groups[key]["csv_score_2024"]
                official_score = rec["score_2024_official"]
                diff = csv_score - official_score
                if abs(diff) < 0.5:
                    lineage.cross_check_passed = True
                else:
                    lineage.cross_check_passed = False
                    lineage.issues.append(f"分数不匹配: CSV={csv_score}, 官方={official_score}, 差={diff}")
                    severity = "ERROR" if abs(diff) >= 10 else "WARN"
                    self.issues.append(ValidationIssue(
                        severity=severity,
                        category="official_mismatch",
                        key=key,
                        field="专业组最低分",
                        expected=str(official_score),
                        actual=str(csv_score),
                        suggestion=f"以官方数据 {official_score} 为准，修正 CSV 中的 {csv_score}",
                        confidence_before="C" if abs(diff) < 10 else "D",
                        confidence_after="C" if abs(diff) < 10 else "D",
                    ))
            else:
                lineage.cross_check_passed = False
                lineage.issues.append("CSV 中缺失该组线数据")
                self.issues.append(ValidationIssue(
                    severity="WARN",
                    category="missing_in_csv",
                    key=key,
                    field="专业组最低分",
                    expected=str(rec["score_2024_official"]),
                    actual=None,
                    suggestion=f"从官方 PDF 补录该组线: {key}={rec['score_2024_official']}",
                    confidence_before="D",
                    confidence_after="C",
                ))
            self.lineage[key] = lineage

    # -----------------------------------------------------------------------
    # 2. 组线 vs 专业线一致性
    # -----------------------------------------------------------------------
    def _validate_group_major_consistency(self):
        df = pd.read_csv(self.csv_path, low_memory=False, dtype=str)

        for _, row in df.iterrows():
            raw_code = str(row.get("院校代码", "")).strip()
            major_score = str(row.get("最低分", "")).strip()
            group_score = str(row.get("专业组最低分", "")).strip()
            major_score_dot1 = str(row.get("最低分.1", "")).strip()
            group_score_dot1 = str(row.get("专业组最低分.1", "")).strip()
            major_score_dot2 = str(row.get("最低分.2", "")).strip()

            # 2024 年
            self._check_major_ge_group(raw_code, major_score, group_score, "2024")
            # 2023 年
            self._check_major_ge_group(raw_code, major_score_dot1, group_score_dot1, "2023")
            # 2022 年
            if major_score_dot2 and major_score_dot2.replace(".", "").isdigit():
                # 2022 年没有组线列，跳过
                pass

    def _check_major_ge_group(self, key: str, major_s: str, group_s: str, year: str):
        """验证专业线 >= 组线（因为专业线不可能低于组线）"""
        if not major_s or not group_s:
            return
        try:
            m = float(major_s)
            g = float(group_s)
        except ValueError:
            return
        if m < g:
            self.issues.append(ValidationIssue(
                severity="ERROR",
                category="group_major_inversion",
                key=key,
                field=f"最低分/{year}",
                expected=f">= {g}",
                actual=str(m),
                suggestion=f"专业线 {m} 低于组线 {g}，数据逻辑错误。建议：将专业线置空，仅保留组线；或核实数据来源",
                confidence_before="A",
                confidence_after="D",
            ))

    # -----------------------------------------------------------------------
    # 3. 异常值检测
    # -----------------------------------------------------------------------
    def _detect_outliers(self):
        df = pd.read_csv(self.csv_path, low_memory=False, dtype=str)
        df_phys = df[df["科类"] == "物理"]

        # 按院校分组，检测同一院校不同组间分数差异过大（>100分）
        for school_name, sub in df_phys.groupby("院校名称"):
            scores = []
            for _, row in sub.iterrows():
                s = str(row.get("专业组最低分", "")).strip()
                if s and s.replace(".", "").isdigit():
                    scores.append(float(s))
            if len(scores) >= 2:
                max_diff = max(scores) - min(scores)
                if max_diff > 100:
                    # 获取该院校的代表性代码
                    raw_code = str(sub.iloc[0].get("院校代码", "")).strip()
                    self.issues.append(ValidationIssue(
                        severity="WARN",
                        category="suspicious_score_spread",
                        key=raw_code,
                        field="专业组最低分",
                        expected="< 100分差距",
                        actual=f"{max_diff}分",
                        suggestion=f"同一院校 {school_name} 不同组线差距 {max_diff} 分，请核实是否有特殊类型招生混入",
                        confidence_before="C",
                        confidence_after="C",
                    ))

    # -----------------------------------------------------------------------
    # 4. 血缘追踪
    # -----------------------------------------------------------------------
    def _build_lineage(self):
        """为所有 CSV 记录生成默认血缘标记"""
        df = pd.read_csv(self.csv_path, low_memory=False, dtype=str)
        for _, row in df.iterrows():
            raw_code = str(row.get("院校代码", "")).strip()
            if not raw_code or raw_code in self.lineage:
                continue
            # 默认标记为第三方来源
            self.lineage[raw_code] = DataLineage(
                source_type="third_party_crawl",
                source_url="https://github.com/Jsoneft/gaokao-zhiyuan",
                source_file="raw_hubei_2024_2025.csv",
                fetched_at="unknown",
                validated_at="2025-06-29",
                validator_version="1.0.0",
                cross_check_passed=False,
                issues=["未通过官方交叉验证"],
            )

    # -----------------------------------------------------------------------
    # 报告生成
    # -----------------------------------------------------------------------
    def _build_report(self) -> dict:
        error_count = sum(1 for i in self.issues if i.severity == "ERROR")
        warn_count = sum(1 for i in self.issues if i.severity == "WARN")
        info_count = sum(1 for i in self.issues if i.severity == "INFO")

        return {
            "summary": {
                "total_issues": len(self.issues),
                "errors": error_count,
                "warnings": warn_count,
                "infos": info_count,
                "csv_path": self.csv_path,
                "official_path": self.official_path,
            },
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "key": i.key,
                    "field": i.field,
                    "expected": i.expected,
                    "actual": i.actual,
                    "suggestion": i.suggestion,
                    "confidence_before": i.confidence_before,
                    "confidence_after": i.confidence_after,
                }
                for i in self.issues
            ],
            "lineage": {
                k: {
                    "source_type": v.source_type,
                    "source_file": v.source_file,
                    "cross_check_passed": v.cross_check_passed,
                    "issues": v.issues,
                }
                for k, v in self.lineage.items()
            },
        }


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Spiral CSV Data Validator")
    parser.add_argument("--csv", default="backend/data/raw_hubei_2024_2025.csv")
    parser.add_argument("--official", default="data_pipeline/official/hubei_2024_physics_official.txt")
    parser.add_argument("--output", default="data_pipeline/reports/validation_report.json")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    validator = DataValidator(args.csv, args.official)
    report = validator.run()

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[validate] 报告已生成: {args.output}")
    print(f"[validate] 总问题数: {report['summary']['total_issues']}")
    print(f"[validate] ERROR: {report['summary']['errors']}, WARN: {report['summary']['warnings']}, INFO: {report['summary']['infos']}")

    # 如果有 ERROR，退出码非 0
    if report['summary']['errors'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
