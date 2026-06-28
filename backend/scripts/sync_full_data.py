"""全量数据同步脚本（2024+2025 新数据链路）。

用法：
    cd backend
    python scripts/sync_full_data.py

前置条件：
    将湖北省教育考试院 2025 官方 PDF 放入 gaokao-agent/.tmp_data/：
        - 2025_physics.pdf   : 本科普通批院校专业组投档线（首选物理）
        - 2025_history.pdf   : 本科普通批院校专业组投档线（首选历史）
        - 2025_rank_physics.pdf / 2025_rank_history.pdf : 普通高考总分一分一段表
    若缺少 PDF，脚本会提示路径并跳过 2025 提取，仅重新导入已有 CSV。
"""

import os
import sys
import subprocess
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db
from services import import_hubei_csv, RAGService
from services.data_importer import import_ranking_json, import_ranking_csv
from services.document_builder import build_all_documents
from models import Document
from recommendation import clear_schools_cache


ROOT = Path(__file__).resolve().parents[2]
TMP_DIR = ROOT / ".tmp_data"
EXTERNAL_DIR = TMP_DIR / "external"
EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

_URLS = {
    "hubei_sql": "https://raw.githubusercontent.com/Jsoneft/gaokao-zhiyuan/main/hubei_data/insert_data_fixed.sql",
    "hubei_ranking_physics": "https://raw.githubusercontent.com/FlySky-z/gaokao-analysis/main/web/data/ranking_score_hubei_physics.json",
    "hubei_ranking_history": "https://raw.githubusercontent.com/FlySky-z/gaokao-analysis/main/web/data/ranking_score_hubei_history.json",
}


def _download(name: str, url: str, dest: Path) -> Path:
    print(f"[download] {name}: {url}")
    urllib.request.urlretrieve(url, str(dest))
    return dest


def _run_script(path: Path) -> None:
    print(f"[run] {path.name}")
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT / "backend"),
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"{path.name} failed with exit code {result.returncode}")


def _seed_rag_documents(db):
    rag = RAGService()
    rag.reset_collection()
    db.query(Document).delete(synchronize_session=False)
    docs = build_all_documents(db)
    for d in docs:
        doc = Document(
            doc_type=d["doc_type"],
            title=d["title"],
            school_name=d.get("school_name"),
            province=d.get("province"),
            source_url=d.get("source_url"),
            content=d["content"][:5000],
        )
        db.add(doc)
    db.commit()
    chunks = rag.index_documents_batch(docs, embed_batch_size=1024)
    print(f"[rag] indexed {len(docs)} docs / {chunks} chunks")


def main():
    # 1. 下载外部数据（专业说明 + 2024 一分一段）
    sql_path = EXTERNAL_DIR / os.path.basename(_URLS["hubei_sql"])
    rank_physics_path = TMP_DIR / os.path.basename(_URLS["hubei_ranking_physics"])
    rank_history_path = TMP_DIR / os.path.basename(_URLS["hubei_ranking_history"])

    _download("hubei_sql", _URLS["hubei_sql"], sql_path)
    _download("hubei_ranking_physics", _URLS["hubei_ranking_physics"], rank_physics_path)
    _download("hubei_ranking_history", _URLS["hubei_ranking_history"], rank_history_path)

    # 2. 从 2025 官方 PDF 提取组线/位次（可选）
    pdf_files = {
        "物理": TMP_DIR / "2025_physics.pdf",
        "历史": TMP_DIR / "2025_history.pdf",
    }
    rank_pdf_files = {
        "物理": TMP_DIR / "2025_rank_physics.pdf",
        "历史": TMP_DIR / "2025_rank_history.pdf",
    }
    missing = [str(p) for p in list(pdf_files.values()) + list(rank_pdf_files.values()) if not p.exists()]
    if missing:
        print("[warning] 以下 2025 官方 PDF 缺失，跳过 2025 提取：")
        for p in missing:
            print(f"  - {p}")
    else:
        _run_script(ROOT / "backend" / "scripts" / "extract_2025_official.py")
        _run_script(ROOT / "backend" / "scripts" / "build_master_csv.py")

    # 3. 导入 CSV + SQL 专业说明
    init_db()
    db = SessionLocal()
    try:
        csv_path = ROOT / "backend" / "data" / "raw_hubei_2024_2025.csv"
        stats = import_hubei_csv(
            db,
            csv_path=str(csv_path),
            clear=True,
            enrich_descriptions=True,
        )
        print("[import]", stats)

        # 4. 导入一分一段表
        if rank_physics_path.exists():
            print(import_ranking_json(db, str(rank_physics_path), "湖北", "物理", 2024))
        if rank_history_path.exists():
            print(import_ranking_json(db, str(rank_history_path), "湖北", "历史", 2024))

        rank_2025_csv = TMP_DIR / "2025_score_rank.csv"
        if rank_2025_csv.exists():
            print(import_ranking_csv(db, str(rank_2025_csv), "湖北", "物理", 2025))
            print(import_ranking_csv(db, str(rank_2025_csv), "湖北", "历史", 2025))

        # 5. RAG 索引：默认跳过，避免 HuggingFace 下载超时；设置 SPIRAL_ENABLE_RAG_SEED=1 可启用
        if os.environ.get("SPIRAL_ENABLE_RAG_SEED", "0").strip() == "1":
            _seed_rag_documents(db)
        else:
            print("[seed] skipped RAG indexing (set SPIRAL_ENABLE_RAG_SEED=1 to enable)")

        clear_schools_cache()
        print("[seed] cleared recommendation schools cache")
    finally:
        db.close()


if __name__ == "__main__":
    main()
