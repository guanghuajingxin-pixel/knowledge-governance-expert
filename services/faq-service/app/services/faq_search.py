import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.models import FaqEntry, Document
from kb_common.clients import es_client
from kb_common.config import get_settings
from app.services.faq_index import _embed

async def search(s: AsyncSession, kb_id: str, query: str, top_k: int = 5) -> dict:
    # 1. PG 关键字精准匹配（question/keywords）
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    q = q.where(FaqEntry.question.ilike(f"%{query}%"))
    precise = (await s.execute(q.limit(top_k))).scalars().all()

    # 2. ES kNN 语义（FAQ 类型）
    qvec = (await _embed([query]))[0]
    index = f"kb_{kb_id.replace('-', '')}"
    sem = []
    if await es_client.es.indices.exists(index=index):
        # NOTE: elasticsearch[async] 8.19.3 的 knn_search() 不接受 size 参数
        # （与 Task 7 同一 bug）。改用 es.search(knn=[...], size=, source=[...])，
        # 这是 kb_common.rag.searcher._knn 已验证可用的调用形式。
        q_knn = {"field": "vector", "query_vector": qvec, "k": top_k,
                 "num_candidates": top_k * 5,
                 "filter": {"term": {"kb_type": "FAQ"}}}
        r = await es_client.es.search(
            index=index, knn=[q_knn], size=top_k,
            source=["text", "faq_entry_id", "faq_answer", "document_id", "kb_type"])
        sem = r["hits"]["hits"]

    # 3. 融合：精准置顶 + 语义补充（按 entry_id 去重）
    seen, results = set(), []
    for e in precise:
        seen.add(str(e.id))
        results.append({"entry_id": str(e.id), "question": e.question, "answer": e.answer,
                        "score": 1.0, "match_type": "precise",
                        "source_document_id": str(e.source_document_id) if e.source_document_id else None})
    for h in sem:
        src = h["_source"]
        eid = src.get("faq_entry_id")
        if eid in seen: continue
        seen.add(eid)
        results.append({"entry_id": eid, "question": src.get("text"), "answer": src.get("faq_answer"),
                        "score": h["_score"], "match_type": "semantic",
                        "source_document_id": src.get("document_id")})
        if len(results) >= top_k: break
    return {"results": results[:top_k], "total": len(results)}
