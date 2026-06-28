"""全量数据同步脚本。

1. 下载/更新 gaokao-zhiyuan 湖北 SQL dump（含专业说明）
2. 下载/更新 FlySky-z/gaokao-analysis 湖北一分一段表
3. 重新导入 CSV、一分一段表
4. 重建 RAG 全量文档索引

用法：
    cd backend
    python scripts/sync_full_data.py
"""

import os
import sys
import urllib.request

# 把 backend 加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db
from services import import_hubei_csv, RAGService
from services.data_importer import import_ranking_json
from services.document_builder import build_all_documents
from models import Document


_EXTERNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".tmp_data", "external")
os.makedirs(_EXTERNAL_DIR, exist_ok=True)

_URLS = {
    "hubei_sql": "https://raw.githubusercontent.com/Jsoneft/gaokao-zhiyuan/main/hubei_data/insert_data_fixed.sql",
    "hubei_ranking_physics": "https://raw.githubusercontent.com/FlySky-z/gaokao-analysis/main/web/data/ranking_score_hubei_physics.json",
    "hubei_ranking_history": "https://raw.githubusercontent.com/FlySky-z/gaokao-analysis/main/web/data/ranking_score_hubei_history.json",
}


def _download(name: str, url: str) -> str:
    dest = os.path.join(_EXTERNAL_DIR, os.path.basename(url))
    print(f"[download] {name}: {url}")
    urllib.request.urlretrieve(url, dest)
    return dest


def main():
    init_db()
    db = SessionLocal()
    try:
        # 1. 下载外部数据
        sql_path = _download("hubei_sql", _URLS["hubei_sql"])
        rank_physics_path = _download("hubei_ranking_physics", _URLS["hubei_ranking_physics"])
        rank_history_path = _download("hubei_ranking_history", _URLS["hubei_ranking_history"])

        # 2. 导入湖北 CSV + SQL 专业说明
        csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "raw_hubei_2024.csv")
        stats = import_hubei_csv(db, csv_path=csv_path, clear=True, enrich_descriptions=True)
        print("[import]", stats)

        # 3. 导入一分一段表（2024 官方数据）
        r1 = import_ranking_json(db, rank_physics_path, "湖北", "物理", 2024)
        r2 = import_ranking_json(db, rank_history_path, "湖北", "历史", 2024)
        print("[ranking]", r1, r2)

        # 4. 重建 RAG 索引
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
    finally:
        db.close()


if __name__ == "__main__":
    main()
