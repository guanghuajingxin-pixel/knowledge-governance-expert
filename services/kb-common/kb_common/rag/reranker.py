from FlagEmbedding import FlagReranker
from kb_common.config import get_settings
_instance = None

def get_reranker():
    global _instance
    if _instance is None:
        _instance = FlagReranker(get_settings().bge_rerank_model, use_fp16=False)
    return _instance

def rerank(query: str, docs: list[dict], top_n: int = 10) -> list[dict]:
    if not docs: return []
    pairs = [[query, d["text"]] for d in docs]
    scores = get_reranker().compute_score(pairs, normalize=True)
    if isinstance(scores, float): scores = [scores]
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)[:top_n]
    for d, sc in ranked: d["rerank_score"] = float(sc)
    return [d for d, _ in ranked]
