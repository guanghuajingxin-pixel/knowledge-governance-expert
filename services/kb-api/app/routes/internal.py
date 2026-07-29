from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.rag import embedder, reranker

router = APIRouter(prefix="/internal", tags=["internal"])

class EmbedIn(BaseModel):
    texts: list[str]
class EmbedOut(BaseModel):
    vectors: list[list[float]]

@router.post("/embed", response_model=EmbedOut)
def embed(body: EmbedIn):
    return EmbedOut(vectors=embedder.embed(body.texts))

class RerankIn(BaseModel):
    query: str
    docs: list[dict]
    top_n: int = 10

@router.post("/rerank")
def rerank_(body: RerankIn):
    return {"results": reranker.rerank(body.query, body.docs, body.top_n)}


@router.post("/index")
async def index_doc(document_id: str, s: AsyncSession = Depends(get_session)):
    from kb_common.models import Document, KnowledgeBase
    from kb_common.rag.indexer import index_document
    from kb_common.clients import minio_client
    doc = await s.get(Document, document_id)
    kb = await s.get(KnowledgeBase, doc.kb_id)
    # 从 MinIO 取解析结果（parsed_path 优先，否则 raw）
    obj = doc.parsed_path or doc.storage_path
    bucket = minio_client.PARSED if doc.parsed_path else minio_client.RAW
    resp = minio_client.minio.get_object(bucket, obj)
    try:
        data = resp.read()
    finally:
        resp.close()
        resp.release_conn()
    markdown = data.decode("utf-8", errors="ignore")
    n = await index_document(s, kb, doc, markdown)
    doc.chunk_count = n; await s.commit()
    return {"chunk_count": n}
