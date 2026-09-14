import os

import httpx

from kb_common.rag import embedder, chunker
from kb_common.clients import es_client
from kb_common.config import get_settings
from kb_common.models import Segment
from datetime import datetime, timezone


async def _embed_internal(texts: list[str]) -> list[list[float]]:
    """通过 kb-api 的 /internal/embed 复用其常驻 BGE-M3（避免 worker 重复加载模型）。"""
    s = get_settings()
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{s.kb_api_internal_url}/internal/embed", json={"texts": texts})
        r.raise_for_status()
        return r.json()["vectors"]


async def index_document(s, kb, doc, markdown: str) -> int:
    """切片 -> 向量化 -> ES bulk -> 回写 segments。返回 chunk 数。"""
    chunks = chunker.chunk(markdown, kb.chunk_strategy, kb.chunk_size, kb.chunk_overlap, kb.delimiter)
    if not chunks: return 0
    texts = [c["text"] for c in chunks]
    # 低内存部署（EMBED_VIA_INTERNAL=true，如 kb-worker 容器）：走 kb-api 内部接口转发外部向量 API；
    # 默认由 kb-api 进程直接调外接 embedder。
    if os.getenv("EMBED_VIA_INTERNAL", "").lower() in ("1", "true", "yes"):
        vectors = await _embed_internal(texts)
    else:
        vectors = embedder.embed(texts)   # 外接 embeddings API
    index = await es_client.ensure_index(str(kb.id))

    docs = []
    segs = []
    for c, vec in zip(chunks, vectors):
        es_id = f"{doc.id}_{c['chunk_index']}"
        docs.append({
            "text": c["text"], "vector": vec,
            "kb_id": str(kb.id), "kb_type": "DOCUMENT",
            "document_id": str(doc.id), "chunk_index": c["chunk_index"],
            "total_chunks": len(chunks), "source_type": "DOCUMENT",
            "source_path": doc.storage_path, "document_title": doc.original_filename,
            "file_type": doc.file_type, "page_number": c["page_number"],
            "directory_id": str(doc.directory_id) if doc.directory_id else None,
            "directory_path": "", "content_hash": c["content_hash"],
            "token_count": c["token_count"], "created_at": datetime.now(timezone.utc).isoformat(),
        })
        segs.append(Segment(document_id=doc.id, es_chunk_id=es_id, chunk_index=c["chunk_index"],
                            content=c["text"], content_hash=c["content_hash"],
                            token_count=c["token_count"], page_number=c["page_number"]))
    await es_client.bulk_index(index, docs)
    s.add_all(segs)
    return len(chunks)
