"""重排模型客户端：全部外接（Jina/SiliconFlow 风格 /rerank），不本地部署 bge-reranker。

未配置 RERANK_API_URL 时 rerank() 直接返回原序前 top_n（跳过重排，RRF/BM25 排序兜底），
searcher 无需感知配置状态。
"""
import httpx
from kb_common.config import get_settings

_session: httpx.Client | None = None


def _client() -> httpx.Client:
    global _session
    if _session is None or _session.is_closed:
        _session = httpx.Client(timeout=30)
    return _session


def rerank(query: str, docs: list[dict], top_n: int = 10) -> list[dict]:
    """外接 rerank API 重排；未配置时跳过重排。"""
    if not docs:
        return []
    s = get_settings()
    if not s.rerank_api_url:
        return docs[:top_n]  # 未配置重排：保序截断，检索侧已有 RRF/BM25 分数
    resp = _client().post(
        s.rerank_api_url,
        headers={"Authorization": f"Bearer {s.rerank_api_key}"} if s.rerank_api_key else {},
        json={"model": s.rerank_model, "query": query,
              "documents": [d.get("text", "") for d in docs]},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    scored = []
    for r in results:
        idx = r.get("index")
        if isinstance(idx, int) and 0 <= idx < len(docs):
            d = dict(docs[idx])
            d["rerank_score"] = float(r.get("relevance_score", 0.0))
            scored.append(d)
    # API 未覆盖的文档保留在尾部（保序）
    covered = {r.get("index") for r in results}
    scored.extend(d for i, d in enumerate(docs) if i not in covered)
    return scored[:top_n]


def close() -> None:
    global _session
    if _session is not None and not _session.is_closed:
        _session.close()
    _session = None
