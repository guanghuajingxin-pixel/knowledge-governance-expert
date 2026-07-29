from elasticsearch import AsyncElasticsearch
from kb_common.config import get_settings

_s = get_settings()
es = AsyncElasticsearch(_s.es_host)

MAPPING = {
  "mappings": {"properties": {
    "text": {"type": "text", "analyzer": "standard"},
    "vector": {"type": "dense_vector", "dims": 1024, "similarity": "cosine", "index": True},
    "kb_id": {"type": "keyword"}, "kb_type": {"type": "keyword"},
    "document_id": {"type": "keyword"}, "faq_entry_id": {"type": "keyword"},
    "chunk_index": {"type": "integer"}, "total_chunks": {"type": "integer"},
    "source_type": {"type": "keyword"}, "source_path": {"type": "keyword"},
    "document_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
    "file_type": {"type": "keyword"}, "page_number": {"type": "integer"},
    "directory_id": {"type": "keyword"}, "directory_path": {"type": "text"},
    "faq_answer": {"type": "text"},
    "preview_url": {"type": "keyword"}, "preview_type": {"type": "keyword"},
    "content_hash": {"type": "keyword"}, "token_count": {"type": "integer"},
    "created_at": {"type": "date"}
  }}
}

async def ensure_index(kb_id: str) -> str:
    name = f"kb_{kb_id.replace('-', '')}"
    if not await es.indices.exists(index=name):
        await es.indices.create(index=name, **MAPPING)
    return name

async def bulk_index(index: str, docs: list[dict]):
    actions = []
    for d in docs:
        actions.append({"index": {"_index": index}})
        actions.append(d)
    await es.bulk(operations=actions, refresh=True)

async def delete_by_doc(index: str, document_id: str):
    await es.delete_by_query(index=index, body={"query": {"term": {"document_id": document_id}}})
