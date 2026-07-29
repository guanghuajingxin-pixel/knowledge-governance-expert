from kb_common.rag import embedder, chunker
from kb_common.clients import es_client
from kb_common.models import Segment
from datetime import datetime, timezone

async def index_document(s, kb, doc, markdown: str) -> int:
    """切片 -> 向量化 -> ES bulk -> 回写 segments。返回 chunk 数。"""
    chunks = chunker.chunk(markdown, kb.chunk_strategy, kb.chunk_size, kb.chunk_overlap, kb.delimiter)
    if not chunks: return 0
    texts = [c["text"] for c in chunks]
    vectors = embedder.embed(texts)   # 本地 FlagEmbedding
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
