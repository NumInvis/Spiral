from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from services import RAGService

router = APIRouter(prefix="/api/rag", tags=["rag"])


def _get_rag():
    return RAGService()


class IndexRequest(BaseModel):
    title: str
    content: str
    doc_type: str  # charter / major / employment / policy
    school_name: Optional[str] = None
    province: Optional[str] = None
    source_url: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    doc_type: Optional[str] = None
    school_name: Optional[str] = None


@router.post("/index")
def index_doc(req: IndexRequest, rag: RAGService = Depends(_get_rag)):
    count = rag.index_document(
        content=req.content,
        title=req.title,
        doc_type=req.doc_type,
        school_name=req.school_name,
        province=req.province,
        source_url=req.source_url,
    )
    return {"indexed_chunks": count, "title": req.title}


@router.post("/query")
def query(req: QueryRequest, rag: RAGService = Depends(_get_rag)):
    filters = {}
    if req.doc_type:
        filters["doc_type"] = req.doc_type
    if req.school_name:
        filters["school_name"] = req.school_name
    return rag.query(req.question, top_k=req.top_k, filters=filters or None)
