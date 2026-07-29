from fastapi import APIRouter
from pydantic import BaseModel
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
