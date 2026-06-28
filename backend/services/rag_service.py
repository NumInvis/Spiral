import os
from typing import List, Dict, Optional, Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct


COLLECTION_NAME = "gaokao_docs"
EMBEDDING_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class RAGService:
    def __init__(self, storage_path: Optional[str] = None, model_name: Optional[str] = None):
        if storage_path is None:
            storage_path = os.path.join(os.path.dirname(__file__), "..", "qdrant_storage")
        self.storage_path = os.path.abspath(storage_path)
        self.model_name = model_name or MODEL_NAME
        self._client: Optional[QdrantClient] = None
        self._model = None

    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(path=self.storage_path)
            self._ensure_collection()
        return self._client

    def _ensure_collection(self):
        if not self._client.collection_exists(COLLECTION_NAME):
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )

    def reset_collection(self):
        """清空向量库集合并重建（用于全量重建 RAG 索引）。"""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        # 本地模式 delete_collection 不会释放 SQLite 空间，直接删除存储目录最干净
        if os.path.exists(self.storage_path):
            import shutil
            shutil.rmtree(self.storage_path)
        # 重新初始化客户端并创建集合
        _ = self.client()

    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        return self.model().encode(texts, convert_to_numpy=True, normalize_embeddings=True).tolist()

    def index_document(
        self,
        content: str,
        title: str,
        doc_type: str,
        school_name: Optional[str] = None,
        province: Optional[str] = None,
        source_url: Optional[str] = None,
        chunk_size: int = 400,
        chunk_overlap: int = 50,
    ) -> int:
        """将长文本切分后索引，返回写入的 chunk 数量。"""
        chunks = self._chunk_text(content, chunk_size, chunk_overlap)
        if not chunks:
            return 0
        vectors = self.embed(chunks)
        points = []
        base_id = abs(hash(title + doc_type + (school_name or ""))) % (10 ** 12)
        for idx, (vec, chunk) in enumerate(zip(vectors, chunks)):
            points.append(PointStruct(
                id=base_id + idx,
                vector=vec,
                payload={
                    "doc_type": doc_type,
                    "title": title,
                    "school_name": school_name,
                    "province": province,
                    "source_url": source_url,
                    "content": chunk,
                },
            ))
        self.client().upsert(collection_name=COLLECTION_NAME, points=points)
        return len(points)

    def index_documents_batch(
        self,
        docs: Iterable[Dict],
        chunk_size: int = 400,
        chunk_overlap: int = 50,
        embed_batch_size: int = 1024,
    ) -> int:
        """批量索引大量文档；内部按 embed_batch_size 分批编码，减少模型调用开销。"""
        client = self.client()
        points: List[PointStruct] = []
        total_chunks = 0

        for doc in docs:
            content = doc.get("content", "")
            if not content or not content.strip():
                continue
            chunks = self._chunk_text(content, chunk_size, chunk_overlap)
            if not chunks:
                continue
            title = doc.get("title", "")
            doc_type = doc.get("doc_type", "")
            school_name = doc.get("school_name")
            province = doc.get("province")
            source_url = doc.get("source_url")
            base_id = abs(hash(title + doc_type + (school_name or "") + str(total_chunks))) % (10 ** 15)
            for idx, chunk in enumerate(chunks):
                points.append(PointStruct(
                    id=base_id + idx,
                    vector=[0.0] * EMBEDDING_DIM,  # 占位，稍后填充
                    payload={
                        "doc_type": doc_type,
                        "title": title,
                        "school_name": school_name,
                        "province": province,
                        "source_url": source_url,
                        "content": chunk,
                    },
                ))
            total_chunks += len(chunks)

        # 分批编码并回填向量
        for i in range(0, len(points), embed_batch_size):
            batch = points[i:i + embed_batch_size]
            vectors = self.embed([p.payload["content"] for p in batch])
            for p, vec in zip(batch, vectors):
                p.vector = vec
            client.upsert(collection_name=COLLECTION_NAME, points=batch)

        return total_chunks

    def query(self, question: str, top_k: int = 5, filters: Optional[Dict] = None) -> Dict:
        vec = self.embed([question])[0]
        filter_obj = None
        if filters:
            from qdrant_client.models import FieldCondition, MatchValue, Filter
            conditions = []
            for k, v in filters.items():
                conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
            filter_obj = Filter(must=conditions)
        response = self.client().query_points(
            collection_name=COLLECTION_NAME,
            query=vec,
            query_filter=filter_obj,
            limit=top_k,
            with_payload=True,
        )
        results = response.points if hasattr(response, "points") else response
        return {
            "question": question,
            "top_k": top_k,
            "results": [
                {
                    "score": round(r.score, 4),
                    "title": r.payload.get("title"),
                    "doc_type": r.payload.get("doc_type"),
                    "school_name": r.payload.get("school_name"),
                    "source_url": r.payload.get("source_url"),
                    "content": r.payload.get("content"),
                }
                for r in results
            ],
        }

    @staticmethod
    def _chunk_text(text: str, size: int, overlap: int) -> List[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunks.append(text[start:end])
            start += size - overlap
            if start >= end:
                break
        return chunks
