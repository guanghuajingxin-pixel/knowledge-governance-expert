"""wiki generator 跨事件循环安全回归。

背景：批处理线程（XXL-Job 执行器）在临时 loop 里 asyncio.run 跑解析刷新，
完成钩子若触碰绑定主 loop 的全局 SessionLocal，会把主连接池连接跨 loop
复用致协议损坏并永久泄漏（PG idle in transaction 堆积 → QueuePool 耗尽 →
全站接口随机 500，典型受害场景：同步队列批量清理报 500）。
"""
import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.services.wiki.generator as gen


class _FakeSession:
    """最小异步会话替身：支持 async with / get / execute / add / commit。"""

    def __init__(self, lib=None, run=None):
        self._lib = lib
        self._run = run
        self.added = []
        self.committed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, pk):
        return self._lib

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self._run)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1


def _doc(library_id=7):
    return SimpleNamespace(library_id=library_id, id=str(uuid4()))


def _recorder(enqueued):
    async def _fake(*a, **kw):
        enqueued.append((a, kw))
    return _fake


async def test_auto_trigger_skips_non_wiki_library(monkeypatch):
    """非 wiki 库（同步批处理绝大多数场景）：直接返回，绝不入队、不另开会话。"""
    enqueued = []
    monkeypatch.setattr(gen, "enqueue_generation", _recorder(enqueued))
    lib = SimpleNamespace(library_type="document", engine_config=None)
    s = _FakeSession(lib=lib)
    await gen.auto_trigger_for_document(s, _doc())
    assert enqueued == []


async def test_auto_trigger_enqueues_wiki_library_with_caller_session(monkeypatch):
    """wiki 库且自动生成开启：用调用方会话查库后入队（参数透传 doc.id）。"""
    enqueued = []
    monkeypatch.setattr(gen, "enqueue_generation", _recorder(enqueued))
    lib = SimpleNamespace(library_type="wiki", engine_config={"wiki": {"auto_generate": True}})
    doc = _doc(library_id=42)
    await gen.auto_trigger_for_document(_FakeSession(lib=lib), doc)
    assert enqueued == [((42, [doc.id],), {"triggered_by": "auto"})]


async def test_auto_trigger_respects_manual_toggle(monkeypatch):
    """wiki 库但自动生成关闭：不入队。"""
    enqueued = []
    monkeypatch.setattr(gen, "enqueue_generation", _recorder(enqueued))
    lib = SimpleNamespace(library_type="wiki", engine_config={"wiki": {"auto_generate": False}})
    await gen.auto_trigger_for_document(_FakeSession(lib=lib), _doc())
    assert enqueued == []


async def test_enqueue_generation_uses_fresh_session_not_global_pool(monkeypatch):
    """enqueue_generation 必须走 fresh_session（双 loop 安全），不碰全局 SessionLocal。"""
    def _boom(*a, **kw):
        raise AssertionError("enqueue_generation 不得使用全局 SessionLocal（跨 loop 污染连接池）")

    monkeypatch.setattr(gen, "SessionLocal", _boom)
    pending = SimpleNamespace(id=uuid4(), kind="ingest", document_ids=[], status="PENDING")
    used_fresh = []

    @asynccontextmanager
    async def fake_fresh_session():
        used_fresh.append(True)
        yield _FakeSession(run=pending)

    monkeypatch.setattr(gen, "fresh_session", fake_fresh_session)
    spawned = []
    monkeypatch.setattr(gen, "_spawn", lambda run_id: spawned.append(run_id))

    run_id = await gen.enqueue_generation(9, ["d1", "d1", "d2"], triggered_by="auto")
    assert used_fresh == [True]
    assert spawned == [pending.id]
    assert run_id == pending.id
    # 同 id 去重
    assert pending.document_ids == ["d1", "d2"]


def test_spawn_hands_off_to_main_loop_from_foreign_loop(monkeypatch):
    """批处理线程临时 loop 里 _spawn 必须把 worker 交回主 loop，而非 create_task 后随临时 loop 丢弃。"""
    main_loop = asyncio.new_event_loop()
    thread = threading.Thread(target=main_loop.run_forever, daemon=True)
    thread.start()
    gen.set_main_loop(main_loop)
    try:
        class _NullAsyncCtx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        done = threading.Event()
        ran_on = []

        async def fake_run_lint(run_id):
            ran_on.append(run_id)
            main_loop.call_soon_threadsafe(done.set)

        class _PendingRun:
            status = "PENDING"
            library_id = 3
            kind = "lint"

        class _SpawnSession(_FakeSession):
            async def get(self, model, pk):
                return _PendingRun()

        monkeypatch.setattr(gen, "SessionLocal", lambda: _SpawnSession())
        monkeypatch.setattr(gen, "_library_lock", lambda lid: _NullAsyncCtx())
        monkeypatch.setattr(gen, "_run_lint", fake_run_lint)

        async def _in_temp_loop():
            gen._spawn(uuid4())  # 当前 running loop 是临时 loop ≠ 主 loop

        asyncio.run(_in_temp_loop())
        # worker 应已投递到主 loop 执行完毕；临时 loop 关闭后仍能完成
        assert done.wait(5), "worker 未被交回主 loop 执行"
        assert len(ran_on) == 1
    finally:
        gen.set_main_loop(None)
        main_loop.call_soon_threadsafe(main_loop.stop)


def test_set_main_loop_reset():
    gen.set_main_loop(None)
    assert gen._main_loop is None
    loop = asyncio.new_event_loop()
    gen.set_main_loop(loop)
    assert gen._main_loop is loop
    gen.set_main_loop(None)
    assert gen._main_loop is None
    loop.close()
