from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import time
from kb_common.database import get_session
from kb_common.models import Document
from kb_common.rag import searcher, tracer
from app.deps import get_current_user, get_principal

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 10
    search_type: str = "hybrid"   # hybrid | semantic | keyword
    filters: dict | None = None


@router.post("")
async def search(body: SearchIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    t0 = time.perf_counter()
    hits = await _dispatch(body, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    results = [tracer.trace(h, dmap) for h in hits]
    took_ms = int((time.perf_counter() - t0) * 1000)
    return {"results": results, "total": len(results), "took_ms": took_ms}


@router.post("/test")
async def search_test(body: SearchIn, u=Depends(get_current_user)):
    """检索测试：返回召回内容、K 值、Score，便于调参。"""
    hits = await _dispatch(body, rerank=False)
    return {"k": body.top_k, "results": [{"text": h.get("text"), "score": h.get("score"),
            "document_title": h.get("document_title"), "chunk_index": h.get("chunk_index")} for h in hits]}


async def _dispatch(body: SearchIn, rerank: bool) -> list[dict]:
    """按 search_type 分发到 semantic/keyword/hybrid；faq 与未知值回退 hybrid。"""
    st = (body.search_type or "hybrid").lower()
    if st == "semantic":
        return await searcher.semantic(body.kb_ids, body.query, body.top_k, body.filters, rerank=rerank)
    if st == "keyword":
        return await searcher.keyword(body.kb_ids, body.query, body.top_k, body.filters)
    return await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=rerank)


class ChatIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 5


@router.post("/chat")
async def chat(body: ChatIn, u=Depends(get_principal), s: AsyncSession = Depends(get_session)):
    from app.services.chat import answer
    return await answer(body.query, body.kb_ids, body.top_k, s)
