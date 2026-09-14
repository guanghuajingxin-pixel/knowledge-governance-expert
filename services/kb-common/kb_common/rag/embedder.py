"""向量模型客户端：全部外接（OpenAI 兼容 /embeddings），不本地部署 BGE-M3。

配置（.env 或 settings 表覆盖）：
- EMBEDDING_BASE_URL  如 https://api.siliconflow.cn/v1（含 /v1，不带 /embeddings）
- EMBEDDING_API_KEY
- EMBEDDING_MODEL     如 BAAI/bge-m3（API 版）；维度须与既有 ES 索引一致
"""
import httpx
from kb_common.config import get_settings

_session: httpx.Client | None = None


def _client() -> httpx.Client:
    global _session
    if _session is None or _session.is_closed:
        _session = httpx.Client(timeout=30)
    return _session


def embed(texts: list[str]) -> list[list[float]]:
    """调外部 embeddings API。未配置时抛 RuntimeError（本地 RAG 检索/入库不可用，
    Dify/RAGFlow 检索不受影响）。"""
    if not texts:
        return []
    s = get_settings()
    if not (s.embedding_base_url and s.embedding_model):
        raise RuntimeError(
            "未配置外接向量模型（EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_API_KEY），"
            "本地 RAG 检索与入库不可用；Dify/RAGFlow 知识库检索不受影响")
    resp = _client().post(
        f"{s.embedding_base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {s.embedding_api_key}"} if s.embedding_api_key else {},
        json={"model": s.embedding_model, "input": texts},
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # 按 index 归位（OpenAI 规范保证返回 index 对应输入顺序）
    vectors: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
    for item in data:
        vectors[item["index"]] = item["embedding"]
    if any(v is None for v in vectors):
        raise RuntimeError(f"向量模型返回数量不足：期望 {len(texts)}，实际 {len(data)}")
    return vectors


def close() -> None:
    global _session
    if _session is not None and not _session.is_closed:
        _session.close()
    _session = None
