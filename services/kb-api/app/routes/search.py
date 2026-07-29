from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session
from kb_common.models import Document
from kb_common.rag import searcher, tracer
from app.deps import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 10
    search_type: str = "hybrid"   # hybrid | semantic | keyword
    filters: dict | None = None


@router.post("")
async def search(body: SearchIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    hits = await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    results = [tracer.trace(h, dmap) for h in hits]
    return {"results": results, "total": len(results)}


@router.post("/test")
async def search_test(body: SearchIn, u=Depends(get_current_user)):
    """检索测试：返回召回内容、K 值、Score，便于调参。"""
    hits = await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=False)
    return {"k": body.top_k, "results": [{"text": h.get("text"), "score": h.get("score"),
            "document_title": h.get("document_title"), "chunk_index": h.get("chunk_index")} for h in hits]}
