import os
from sqlalchemy.orm import Session

from database import SessionLocal, init_db
from models import Document
from services import import_hubei_csv, RAGService
from services.data_importer import import_ranking_json, import_ranking_csv
from services.document_builder import build_all_documents
from recommendation import clear_schools_cache


def seed(skip_rag: bool = None):
    if skip_rag is None:
        skip_rag = os.environ.get("SPIRAL_SKIP_RAG_SEED", "0").strip() == "1"
    init_db()
    db: Session = SessionLocal()
    try:
        csv_path = os.path.join(os.path.dirname(__file__), "data", "raw_hubei_2024_2025.csv")
        stats = import_hubei_csv(db, csv_path=csv_path, clear=True, enrich_descriptions=True)
        print(f"[seed] imported hubei csv: {stats}")

        # 导入 2024/2025 一分一段表
        rank_2024_physics = os.path.join(os.path.dirname(__file__), "..", ".tmp_data", "hubei_data_ranking_score_hubei_physics.json")
        rank_2024_history = os.path.join(os.path.dirname(__file__), "..", ".tmp_data", "hubei_data_ranking_score_hubei_history.json")
        rank_2025_csv = os.path.join(os.path.dirname(__file__), "..", ".tmp_data", "2025_score_rank.csv")
        if os.path.exists(rank_2024_physics):
            print(import_ranking_json(db, rank_2024_physics, "湖北", "物理", 2024))
        if os.path.exists(rank_2024_history):
            print(import_ranking_json(db, rank_2024_history, "湖北", "历史", 2024))
        if os.path.exists(rank_2025_csv):
            print(import_ranking_csv(db, rank_2025_csv, "湖北", "物理", 2025))
            print(import_ranking_csv(db, rank_2025_csv, "湖北", "历史", 2025))

        if not skip_rag:
            _seed_rag_documents(db)
        else:
            print("[seed] skipped RAG indexing (SPIRAL_SKIP_RAG_SEED=1)")
        # 数据已重建，清除 recommendation 内存缓存
        clear_schools_cache()
        print("[seed] cleared recommendation schools cache")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def _seed_rag_documents(db: Session):
    """基于已导入的全量真实数据构建 RAG 知识库，禁止手写示例文档。"""
    # 清空旧索引
    rag = RAGService()
    rag.reset_collection()
    db.query(Document).delete(synchronize_session=False)

    # 从数据库全量生成文档
    docs = build_all_documents(db)

    # 写入关系库（轻量记录，便于 /api/schools/{id}/documents 等查询）
    for d in docs:
        doc = Document(
            doc_type=d["doc_type"],
            title=d["title"],
            school_name=d.get("school_name"),
            province=d.get("province"),
            source_url=d.get("source_url"),
            content=d["content"][:5000],  # 关系库只存摘要，全文在向量库
        )
        db.add(doc)
    db.commit()

    # 批量索引到向量库
    indexed_chunks = rag.index_documents_batch(docs, embed_batch_size=1024)
    print(f"[seed] indexed {len(docs)} documents ({indexed_chunks} chunks) into RAG")


if __name__ == "__main__":
    seed()
