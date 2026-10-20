"""向量模型客户端：全部外接（OpenAI 兼容 /embeddings），不本地部署 BGE-M3。

配置（.env 或 settings 表覆盖）：
- EMBEDDING_BASE_URL  如 https://api.siliconflow.cn/v1（含 /v1，不带 /embeddings）
- EMBEDDING_API_KEY
- EMBEDDING_MODEL     如 BAAI/bge-m3（API 版）；维度须与既有 ES 索引一致

服务不可达时的双重保护：
- 短超时（EMBEDDING_TIMEOUT_SECONDS，默认 5s）：单次调用不再等满 30s；
- 连续失败熔断（3 次失败 → 5 分钟冷却期内直接快速失败，不打网络请求；
  冷却期满放行一次探测，成功即恢复）——模型服务宕机时检索链路秒级降级
  到词项检索，而不是每次都陪着等超时。
"""
import httpx
from kb_common.config import get_settings
from kb_common.rag.circuit_breaker import CircuitBreaker

_session: httpx.Client | None = None
_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)


class EmbeddingError(RuntimeError):
    """向量模型调用失败（未配置 / 服务不可达 / 响应异常），调用方应转为用户可读提示。"""


def _client() -> httpx.Client:
    global _session
    if _session is None or _session.is_closed:
        _session = httpx.Client(timeout=get_settings().embedding_timeout_seconds)
    return _session


def embed(texts: list[str]) -> list[list[float]]:
    """调外部 embeddings API。未配置/调用失败时抛 EmbeddingError（本地 RAG 检索/入库不可用，
    Dify/RAGFlow 检索不受影响）。熔断打开时同样抛 EmbeddingError，调用方按既有逻辑降级。"""
    if not texts:
        return []
    s = get_settings()
    if not (s.embedding_base_url and s.embedding_model):
        raise EmbeddingError(
            "未配置外接向量模型（EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_API_KEY），"
            "本地 RAG 检索与入库不可用；Dify/RAGFlow 知识库检索不受影响")
    if _breaker.is_open:
        raise EmbeddingError(
            "向量模型服务近期连续失败已熔断（冷却期内自动降级），请稍后重试或检查模型服务状态")
    try:
        resp = _client().post(
            f"{s.embedding_base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {s.embedding_api_key}"} if s.embedding_api_key else {},
            json={"model": s.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
    except httpx.HTTPError as e:
        _breaker.record_failure()
        raise EmbeddingError("向量模型调用失败，请修改后重试") from e
    except (KeyError, ValueError) as e:
        # 响应结构异常是服务侧问题而非网络问题，同样计入失败
        _breaker.record_failure()
        raise EmbeddingError("向量模型调用失败，请修改后重试") from e
    # 按 index 归位（OpenAI 规范保证返回 index 对应输入顺序）
    vectors: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
    for item in data:
        vectors[item["index"]] = item["embedding"]
    if any(v is None for v in vectors):
        raise EmbeddingError(f"向量模型返回数量不足：期望 {len(texts)}，实际 {len(data)}")
    _breaker.record_success()
    return vectors


def close() -> None:
    global _session
    if _session is not None and not _session.is_closed:
        _session.close()
    _session = None
