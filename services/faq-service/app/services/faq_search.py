"""FAQ 检索：问题（含相似问）匹配 → 答案召回。

两路融合：
1. PG 精准匹配：question / similar_questions / keywords 任一 ilike 命中即置顶
2. ES kNN 语义检索：主问题与相似问均已向量化，语义命中任一变体即召回同一条答案
"""
import httpx
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.models import FaqEntry
from kb_common.clients import es_client
from app.services.faq_index import _embed


def _match_field(entry: FaqEntry, query: str) -> str:
    """返回精准命中的字段口径：优先标准问题，其次相似问，最后关键词。"""
    if query in entry.question:
        return entry.question
    for s in (entry.similar_questions or []):
        if query in s:
            return s
    for k in (entry.keywords or []):
        if query in k:
            return k
    return entry.question


def _item(entry: FaqEntry, score: float, match_type: str, matched: str | None = None) -> dict:
    return {
        "entry_id": str(entry.id), "question": entry.question,
        "matched_question": matched or entry.question,
        "answer": entry.answer, "score": score, "match_type": match_type,
        "similar_questions": list(entry.similar_questions or []),
        "source_document_id": str(entry.source_document_id) if entry.source_document_id else None,
    }


async def search(s: AsyncSession, kb_id: str, query: str, top_k: int = 5) -> dict:
    pattern = f"%{query}%"
    # 1. PG 关键字精准匹配（问题/相似问/关键词）
    q = select(FaqEntry).where(
        FaqEntry.kb_id == kb_id,
        or_(
            FaqEntry.question.ilike(pattern),
            func.array_to_string(FaqEntry.similar_questions, ' || ').ilike(pattern),
            func.array_to_string(FaqEntry.keywords, ' || ').ilike(pattern),
        ),
    )
    precise = (await s.execute(q.limit(top_k))).scalars().all()

    # 2. ES kNN 语义（主问题与相似问均已独立索引）
    # 向量服务不可用时跳过语义通道（fail-soft），精准匹配结果不受影响
    warnings = []
    sem = []
    try:
        qvec = (await _embed([query]))[0]
    except Exception:
        warnings.append("语义检索暂不可用，已返回精准匹配结果")
    else:
        index = f"kb_{kb_id.replace('-', '')}"
        if await es_client.es.indices.exists(index=index):
            # NOTE: elasticsearch[async] 8.19.3 的 knn_search() 不接受 size 参数
            # （与 Task 7 同一 bug）。改用 es.search(knn=[...], size=, source=[...])，
            # 这是 kb_common.rag.searcher._knn 已验证可用的调用形式。
            q_knn = {"field": "vector", "query_vector": qvec, "k": top_k,
                     "num_candidates": top_k * 5,
                     "filter": {"term": {"kb_type": "FAQ"}}}
            try:
                r = await es_client.es.search(
                    index=index, knn=[q_knn], size=top_k,
                    source=["text", "document_title", "faq_entry_id", "faq_answer",
                            "document_id", "kb_type"])
                sem = r["hits"]["hits"]
            except Exception:
                warnings.append("语义检索暂不可用，已返回精准匹配结果")

    # 3. 融合：精准置顶 + 语义补充（按 entry_id 去重）
    seen, results = set(), []
    for e in precise:
        seen.add(str(e.id))
        results.append(_item(e, 1.0, "precise", _match_field(e, query)))
    for h in sem:
        src = h["_source"]
        eid = src.get("faq_entry_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        # ES 命中的是向量化文本（可能是相似问），标准问题以 document_title 为准
        results.append({
            "entry_id": eid, "question": src.get("document_title"),
            "matched_question": src.get("text"),
            "answer": src.get("faq_answer"), "score": h["_score"],
            "match_type": "semantic", "similar_questions": [],
            "source_document_id": src.get("document_id"),
        })
        if len(results) >= top_k:
            break
    return {"results": results[:top_k], "total": len(results), "warnings": warnings}
