"""外接模型客户端的短超时与连续失败熔断测试。

背景：模型服务（embedding/rerank）宕机时，旧实现每次调用等满 30s 超时，
检索串行多库累计 60~95s，拖垮连接池后整个应用卡顿。熔断器保证连续失败后
快速失败，调用方按既有逻辑秒级降级。
"""
import httpx
import pytest

from kb_common.rag import embedder, reranker
from kb_common.rag.circuit_breaker import CircuitBreaker
from kb_common.rag.embedder import EmbeddingError


@pytest.fixture(autouse=True)
def _reset_modules(monkeypatch):
    """每个用例独立熔断状态与 HTTP 客户端。"""
    embedder._breaker.reset()
    reranker._breaker.reset()
    monkeypatch.setattr(embedder, "_session", None)
    monkeypatch.setattr(reranker, "_session", None)
    yield


class TestCircuitBreaker:
    def test_closed_by_default(self):
        assert CircuitBreaker().is_open is False

    def test_opens_after_consecutive_failures(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=300)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is False  # 未达阈值
        cb.record_failure()
        assert cb.is_open is True

    def test_success_resets_counter(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=300)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.is_open is False  # 成功清零，重新累计

    def test_half_open_after_cooldown_then_reopen_on_probe_failure(self, monkeypatch):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open is True
        # 模拟冷却期满
        import kb_common.rag.circuit_breaker as mod
        base = mod.time.monotonic()
        monkeypatch.setattr(mod.time, "monotonic", lambda: base + 61)
        assert cb.is_open is False  # 半开：放行探测
        cb.record_failure()  # 探测仍失败
        assert cb.is_open is True   # 立即重新打开

    def test_half_open_success_recovers(self, monkeypatch):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        for _ in range(3):
            cb.record_failure()
        import kb_common.rag.circuit_breaker as mod
        base = mod.time.monotonic()
        monkeypatch.setattr(mod.time, "monotonic", lambda: base + 61)
        assert cb.is_open is False
        cb.record_success()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is False  # 已恢复 CLOSED，单次失败不触发


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0

    def post(self, *a, **kw):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.response


def _settings(monkeypatch, **overrides):
    from kb_common.config import Settings
    values = {
        "embedding_base_url": "http://models.test/v1",
        "embedding_api_key": "k",
        "embedding_model": "bge-m3",
        "embedding_timeout_seconds": 5.0,
        "rerank_api_url": "http://models.test/v1/rerank",
        "rerank_api_key": "k",
        "rerank_model": "bge-reranker-v2-m3",
        "rerank_timeout_seconds": 5.0,
    }
    values.update(overrides)
    s = Settings(**values)
    monkeypatch.setattr(embedder, "get_settings", lambda: s)
    monkeypatch.setattr(reranker, "get_settings", lambda: s)


class TestEmbedderBreaker:
    def test_timeout_is_short(self, monkeypatch):
        _settings(monkeypatch)
        captured = {}

        real_client_cls = httpx.Client

        class _Client(real_client_cls):
            def __init__(self, timeout=None, **kw):
                captured["timeout"] = timeout
                super().__init__(timeout=timeout, **kw)

        monkeypatch.setattr(embedder.httpx, "Client", _Client)
        with pytest.raises(EmbeddingError):
            embedder.embed(["你好"])
        assert captured["timeout"] == 5.0

    def test_opens_after_three_failures_no_more_requests(self, monkeypatch):
        _settings(monkeypatch)
        fake = _FakeClient(exc=httpx.ConnectTimeout("unreachable"))
        monkeypatch.setattr(embedder, "_client", lambda: fake)
        for _ in range(3):
            with pytest.raises(EmbeddingError):
                embedder.embed(["q"])
        assert fake.calls == 3
        # 熔断打开：第 4 次不再发网络请求，直接快速失败
        with pytest.raises(EmbeddingError, match="熔断"):
            embedder.embed(["q"])
        assert fake.calls == 3

    def test_success_keeps_breaker_closed(self, monkeypatch):
        _settings(monkeypatch)
        resp = httpx.Response(200, request=httpx.Request("POST", "http://x"),
                              json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
        ok = _FakeClient(response=resp)
        bad = _FakeClient(exc=httpx.ConnectTimeout("unreachable"))
        calls = {"n": 0}

        def alternating():
            calls["n"] += 1
            return bad if calls["n"] % 2 else ok

        monkeypatch.setattr(embedder, "_client", alternating)
        for i in range(4):  # 失败/成功交替：永远到不了连续 3 次失败
            if i % 2 == 0:
                with pytest.raises(EmbeddingError):
                    embedder.embed(["q"])
            else:
                embedder.embed(["q"])
        assert embedder._breaker.is_open is False

    def test_unconfigured_raises_without_network(self, monkeypatch):
        _settings(monkeypatch, embedding_base_url="", embedding_model="")
        fake = _FakeClient()
        monkeypatch.setattr(embedder, "_client", lambda: fake)
        with pytest.raises(EmbeddingError, match="未配置"):
            embedder.embed(["q"])
        assert fake.calls == 0


class TestRerankerBreaker:
    def test_network_failure_fails_soft_keeps_order(self, monkeypatch):
        _settings(monkeypatch)
        fake = _FakeClient(exc=httpx.ConnectTimeout("unreachable"))
        monkeypatch.setattr(reranker, "_client", lambda: fake)
        docs = [{"text": "a", "score": 1.0}, {"text": "b", "score": 0.5}]
        out = reranker.rerank("q", docs, top_n=2)
        assert [d["text"] for d in out] == ["a", "b"]  # 原序返回，不抛异常

    def test_open_breaker_skips_without_request(self, monkeypatch):
        _settings(monkeypatch)
        fake = _FakeClient(exc=httpx.ConnectTimeout("unreachable"))
        monkeypatch.setattr(reranker, "_client", lambda: fake)
        for _ in range(3):
            reranker.rerank("q", [{"text": "x"}], top_n=1)
        assert fake.calls == 3
        out = reranker.rerank("q", [{"text": "x"}, {"text": "y"}], top_n=1)
        assert fake.calls == 3  # 熔断打开后不再发请求
        assert len(out) == 1

    def test_unconfigured_returns_top_n(self, monkeypatch):
        _settings(monkeypatch, rerank_api_url="")
        fake = _FakeClient()
        monkeypatch.setattr(reranker, "_client", lambda: fake)
        docs = [{"text": "a"}, {"text": "b"}]
        assert reranker.rerank("q", docs, top_n=1) == [{"text": "a"}]
        assert fake.calls == 0
