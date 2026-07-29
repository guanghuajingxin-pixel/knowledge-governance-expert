from kb_common.clients import es_client
from kb_common.rag import embedder, reranker
from elasticsearch import AsyncElasticsearch

K_RRF = 60


async def _knn(es: AsyncElasticsearch, index: str, vector, top_k: int, filters: dict):
    q = {"field": "vector", "query_vector": vector, "k": top_k, "num_candidates": top_k * 5}
    if filters.get("directory_ids"):
        q["filter"] = {"terms": {"directory_id": filters["directory_ids"]}}
    r = await es.search(
        index=index,
        knn=[q],
        size=top_k,
        source=["text", "document_id", "document_title", "chunk_index",
                "page_number", "source_path", "file_type", "content_hash",
                "directory_id", "kb_type", "faq_entry_id", "faq_answer"],
    )
    return [(h["_id"], h["_score"], h["_source"]) for h in r["hits"]["hits"]]


async def _bm25(es: AsyncElasticsearch, index: str, query: str, top_k: int, filters: dict):
    must = [{"match": {"text": query}}]
    if filters.get("directory_ids"):
        must.append({"terms": {"directory_id": filters["directory_ids"]}})
    r = await es.search(index=index, query={"bool": {"must": must}}, size=top_k,
                        source=True)
    return [(h["_id"], h["_score"], h["_source"]) for h in r["hits"]["hits"]]


def _rrf(ranklists: list[list[tuple]], top_k: int) -> list[tuple]:
    """多路结果 RRF 融合。ranklists: 每路 [(id, score, src)]，按出现顺序即排名。"""
    scores = {}
    src_map = {}
    for rl in ranklists:
        for rank, (hid, _score, src) in enumerate(rl):
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (K_RRF + rank + 1)
            src_map[hid] = src
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [(hid, sc, src_map[hid]) for hid, sc in ordered]


async def hybrid(kb_ids: list[str], query: str, top_k: int = 10,
                 filters: dict | None = None, rerank: bool = True) -> list[dict]:
    filters = filters or {}
    qvec = embedder.embed([query])[0]
    es = es_client.es
    merged = []
    for kb_id in kb_ids:
        index = f"kb_{kb_id.replace('-', '')}"
        if not await es.indices.exists(index=index):
            continue
        knn = await _knn(es, index, qvec, top_k, filters)
        bm25 = await _bm25(es, index, query, top_k, filters)
        merged.append(knn)
        merged.append(bm25)
    fused = _rrf(merged, top_k * 5 if rerank else top_k)
    docs = [{"id": hid, "score": sc, **src} for hid, sc, src in fused]
    if rerank and docs:
        docs = reranker.rerank(query, docs, top_n=top_k)
        # rerank 后补回原始 score
    return docs[:top_k]
