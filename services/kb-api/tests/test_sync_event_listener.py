"""钉钉知识库变更事件监听（自动同步触发器）单测 + 编目 trigger=auto 行为。

覆盖：事件全文与启用源 workspace_id 匹配、去抖合并、静默期补跑预约、
未知/异常事件 fail-soft、订阅 topic 三级配置、凭据缺失降级、
run_catalog auto 触发的 operator/静默期兜底/手动不受静默期约束。
"""
import asyncio
import unittest
import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kb_common.models import (
    LibraryDocument, SyncDocumentMapping, SyncFailure, SyncLog, SyncRun,
    SyncSource, SyncTask, Setting,
)

from app.services.sync import catalog, event_listener as el, scheduler


def _sqlite_sessions(*models):
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    for m in models:
        m.__table__.create(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _patch_session(module, sessions):
    return patch.object(module, 'SyncSessionLocal', sessions)


class _BoomSession:
    """async context manager：一进入就炸（模拟 DB 不可用）。"""

    async def __aenter__(self):
        raise RuntimeError('db down')

    async def __aexit__(self, *exc):
        return False


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeAsyncSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query):
        return _RowsResult(self._rows)


def _boom_factory():
    return _BoomSession()


class MatchSourcesTest(unittest.TestCase):
    """事件全文 ↔ 启用源 workspace_id 子串匹配。"""

    def setUp(self):
        self.engine, self.sessions = _sqlite_sessions(SyncSource)
        self.p = patch('app.services.sync.sync_database.SyncSessionLocal', self.sessions)
        self.p.start()
        self.addCleanup(self.p.stop)

    def tearDown(self):
        self.engine.dispose()

    def _source(self, db, **kw):
        fields = dict(name='s', workspace_id='ws-123', root_node_id='r',
                      dataset_name='t', enabled=True)
        fields.update(kw)
        src = SyncSource(**fields)
        db.add(src)
        db.commit()
        return src

    def test_matches_enabled_source_by_workspace_substring(self):
        with self.sessions() as db:
            src = self._source(db)
            hits = el._match_sources('xxxx "workspaceId": "ws-1234567890" yyyy')
            self.assertEqual(hits, [src.id])

    def test_excludes_disabled_import_once_and_blank_workspace(self):
        with self.sessions() as db:
            self._source(db)  # 启用源（对照）
            self._source(db, enabled=False)
            self._source(db, import_once=True)
            self._source(db, workspace_id='')
        hits = el._match_sources('ws-123')
        self.assertEqual(len(hits), 1)

    def test_no_hit_returns_empty(self):
        with self.sessions() as db:
            self._source(db)
        self.assertEqual(el._match_sources('unrelated-event'), [])

    def test_db_failure_returns_empty_not_raise(self):
        with patch('app.services.sync.sync_database.SyncSessionLocal', _boom_factory):
            self.assertEqual(el._match_sources('ws-123'), [])


class DebounceTest(unittest.TestCase):
    """去抖合并：同源窗口内多次事件合并一次编目；静默期补跑同通道。"""

    def setUp(self):
        el.cancel_pending()
        self.fired = []

    def tearDown(self):
        el.cancel_pending()

    def _patch_fire(self):
        p = patch.object(el, '_fire_catalog', side_effect=lambda sid: self.fired.append(sid))
        p.start()
        self.addCleanup(p.stop)

    def test_same_source_merges_to_one_catalog(self):
        self._patch_fire()
        el.schedule_catalog(1, 1.0)
        el.schedule_catalog(1, 1.0)
        el.schedule_catalog(1, 1.0)
        import time
        time.sleep(1.3)
        self.assertEqual(self.fired, [1])

    def test_distinct_sources_fire_independently(self):
        self._patch_fire()
        el.schedule_catalog(1, 1.0)
        el.schedule_catalog(2, 1.0)
        import time
        time.sleep(1.3)
        self.assertEqual(sorted(self.fired), [1, 2])

    def test_cancel_pending_drops_scheduled(self):
        self._patch_fire()
        el.schedule_catalog(1, 30.0)
        el.cancel_pending()
        import time
        time.sleep(0.1)
        self.assertEqual(self.fired, [])

    def test_recheck_uses_same_channel(self):
        self._patch_fire()
        el.schedule_recheck(7, 1.0)
        import time
        time.sleep(1.3)
        self.assertEqual(self.fired, [7])

    def test_debounce_seconds_floor(self):
        # 配置过小 → 至少 5s；非法值 → 默认 30s（0/falsy 同样回默认）
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_sync_debounce_seconds=0.5)):
            self.assertEqual(el._debounce_seconds(), 5.0)
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_sync_debounce_seconds='abc')):
            self.assertEqual(el._debounce_seconds(), 30.0)


class EventHandlerTest(unittest.TestCase):
    """事件回调：命中调度、未命中忽略、异常事件不炸且恒 ACK。"""

    def setUp(self):
        el.cancel_pending()
        self.scheduled = []

    def tearDown(self):
        el.cancel_pending()

    def _process(self, data):
        p_match = patch.object(el, '_match_sources', return_value=self.hits)
        p_sched = patch.object(el, 'schedule_catalog',
                               side_effect=lambda sid: self.scheduled.append(sid))
        with p_match, p_sched:
            return asyncio.run(el._DocEventHandler().process(SimpleNamespace(data=data)))

    def test_hit_schedules_catalog_for_each_source(self):
        self.hits = [3, 5]
        status, msg = self._process({'eventType': 'doc_spaces_node_change',
                                     'workspaceId': 'ws-1'})
        # AckMessage.STATUS_OK == 200
        self.assertEqual((status, msg), (200, 'OK'))
        self.assertEqual(self.scheduled, [3, 5])

    def test_miss_ignored(self):
        self.hits = []
        self._process({'eventType': 'doc_node_edited'})
        self.assertEqual(self.scheduled, [])

    def test_malformed_event_never_raises(self):
        self.hits = []
        for data in (None, {}, {'eventType': 123, 'body': object()}):
            status, _msg = self._process(data)
            self.assertEqual(status, 200)


class ResolveTopicsTest(unittest.TestCase):
    """订阅事件三级配置：Setting 表 > .env > 代码默认。"""

    def test_env_override_when_db_down(self):
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_sync_event_topics='evt_a, evt_b')), \
             patch('kb_common.database.SessionLocal', _boom_factory):
            topics = asyncio.run(el._resolve_topics())
        self.assertEqual(topics, ['evt_a', 'evt_b'])

    def test_db_setting_wins_over_env(self):
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_sync_event_topics='evt_a')), \
             patch('kb_common.database.SessionLocal',
                   lambda: _FakeAsyncSession([SimpleNamespace(value='db_topic')])):
            topics = asyncio.run(el._resolve_topics())
        self.assertEqual(topics, ['db_topic'])

    def test_default_when_nothing_configured(self):
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_sync_event_topics='')), \
             patch('kb_common.database.SessionLocal',
                   lambda: _FakeAsyncSession([])):
            topics = asyncio.run(el._resolve_topics())
        self.assertEqual(topics, list(el.DEFAULT_EVENT_TOPICS))


class RefreshListenerFailSoftTest(unittest.TestCase):
    """凭据缺失：记告警、不启动监听、不影响手动同步。"""

    def test_missing_credentials_disables_listener(self):
        el._state.update(enabled=False, last_error='')
        with patch.object(el, 'get_settings', lambda: SimpleNamespace(
                dingtalk_app_key='', dingtalk_app_secret='',
                dingtalk_sync_event_topics='')), \
             patch('kb_common.database.SessionLocal',
                   lambda: _FakeAsyncSession([])):
            asyncio.run(el.refresh_listener())
        self.assertTrue(el._state['enabled'])
        self.assertIn('未配置', el._state['last_error'])
        self.assertIsNone(el._task)
        self.assertFalse(el._state['running'])


async def _sdk_like_start() -> None:
    """复刻 dingtalk_stream SDK start() 的吞取消结构：CancelledError 被 except
    捕获后落到重连 sleep 上（该 sleep 在 except 块内，第二刀会逃出 while）。"""
    while True:
        try:
            await asyncio.sleep(3600)          # 模拟 websocket 读
        except asyncio.CancelledError:         # SDK：当作网络异常捕获
            await asyncio.sleep(10)            # SDK：重连前 sleep（第二刀落点）


async def _stubborn_swallowing_task(deadline: float = 0.5) -> None:
    """比 SDK 更顽固：try 内捕获任意多次 cancel（双刀也无效），验证有界等待
    兜底不挂死；deadline 后自行退出避免测试 teardown 挂起。"""
    loop = asyncio.get_running_loop()
    end = loop.time() + deadline
    while loop.time() < end:
        try:
            await asyncio.sleep(max(0.0, end - loop.time()))
        except asyncio.CancelledError:
            continue


class StopListenerSwallowedCancelTest(unittest.TestCase):
    """回归：SDK start() 吞 CancelledError → 单次 cancel 杀不死任务 → 曾经把
    uvicorn 热重载 shutdown 永久挂住（旧进程泄漏 PG 连接打满 max_connections）。"""

    def test_stop_stream_task_double_cancel_kills_sdk_like_task(self):
        async def scenario():
            from app.services.dingtalk_bot import stop_stream_task
            task = asyncio.create_task(_sdk_like_start())
            await asyncio.sleep(0.01)
            return await stop_stream_task(task, timeout=2), task.done()

        ok, done = asyncio.run(scenario())
        self.assertTrue(ok)
        self.assertTrue(done)

    def test_stop_stream_task_bounded_wait_on_stubborn_task(self):
        async def scenario():
            from app.services.dingtalk_bot import stop_stream_task
            task = asyncio.create_task(_stubborn_swallowing_task())
            await asyncio.sleep(0.01)
            return await stop_stream_task(task, timeout=0.2), task.done()

        ok, done = asyncio.run(scenario())
        self.assertFalse(ok)   # 有界等待超时放弃，而不是永久挂死
        self.assertFalse(done)

    def test_stop_listener_terminates_sdk_like_task(self):
        async def scenario():
            el._task = asyncio.create_task(_sdk_like_start())
            await asyncio.sleep(0.01)
            await el.stop_listener()          # 曾经在这里永久挂住
            return el._task.done() if el._task else True

        self.assertTrue(asyncio.run(scenario()))
        self.assertIsNone(el._task)
        self.assertFalse(el._state['running'])
        self.assertFalse(el._state['connected'])


class _FullDocStub:
    """LibraryDocument SQLite 替身（无 PG ARRAY 列，覆盖 run_catalog 用到的字段）。"""

    @staticmethod
    def build():
        from sqlalchemy import Column, Integer, String, Text
        from sqlalchemy.dialects.postgresql import UUID
        from sqlalchemy.orm import declarative_base

        class _Doc(declarative_base()):
            __tablename__ = 'library_documents'
            id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
            library_id = Column(Integer)
            name = Column(String(500))
            source = Column(String(50))
            storage_path = Column(String(1000))
            size = Column(Integer)
            status = Column(String(20))
            progress = Column(Integer)
            message = Column(Text)
            chunk_count = Column(Integer)
            source_url = Column(String(1000))
            source_workspace_name = Column(String(200))
            updated_by = Column(String(100))

        return _Doc


def _now_ms():
    import time
    return int(time.time() * 1000)


class CatalogAutoTriggerTest(unittest.TestCase):
    """run_catalog(trigger='auto')：operator 默认系统、静默期预约补跑、手动不受静默期约束。"""

    def setUp(self):
        self.engine, self.sessions = _sqlite_sessions(
            SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask, Setting)
        self.doc_cls = _FullDocStub.build()
        self.doc_cls.__table__.create(self.engine)
        self._mk_source()
        self.rechecks = []
        self.patches = [
            _patch_session(catalog, self.sessions),
            patch.object(catalog, 'LibraryDocument', self.doc_cls),
            patch.object(catalog, 'get_settings', lambda: SimpleNamespace(
                sync_max_depth=5, sync_max_results_per_page=100, sync_edit_quiet_minutes=10,
                sync_skip_ext_list=[])),
            patch.object(catalog, 'make_dingtalk_client',
                         lambda db, operator_union_id='': self._fake_dt()),
            patch.object(catalog, 'make_library_backend', lambda source: self._fake_backend()),
            patch('app.services.dingtalk_operator.resolve_source_operator_sync',
                  lambda db, source: ('', '测试身份')),
            patch.object(scheduler, 'trigger_batch_once', lambda: None),
            patch.object(el, 'schedule_recheck',
                         side_effect=lambda sid, delay: self.rechecks.append((sid, delay))),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.engine.dispose()

    def _mk_source(self):
        with self.sessions() as db:
            src = SyncSource(name='自动源', workspace_id='ws-9', root_node_id='r',
                             dataset_id='1', dataset_name='t', enabled=True)
            db.add(src)
            db.commit()
            self.source_id = src.id

    @staticmethod
    def _fake_dt():
        return SimpleNamespace(walk_tree_iter=lambda *a, **k: iter([]),
                               list_workspaces=lambda: [], close=lambda: None)

    @staticmethod
    def _fake_backend():
        return SimpleNamespace(library_id=1, delete_document=lambda *a, **k: None,
                               close=lambda: None)

    def _run(self, trigger, operator=''):
        # 清掉上一用例遗留的 running run（批处理未消费完会跳过新一轮编目）
        with self.sessions() as db:
            db.query(SyncRun).filter_by(source_id=self.source_id).delete()
            db.commit()
        return catalog.run_catalog(self.source_id, trigger, operator)

    def _last_run(self):
        with self.sessions() as db:
            run = db.query(SyncRun).order_by(SyncRun.id.desc()).first()
            db.refresh(run)
            return run

    def test_auto_trigger_defaults_operator_and_records_trigger(self):
        result = self._run('auto')
        self.assertEqual(result['status'], 'success')
        run = self._last_run()
        self.assertEqual(run.trigger, 'auto')
        self.assertEqual(run.operator, '系统')

    def test_manual_trigger_keeps_operator(self):
        self._run('manual', '王五')
        run = self._last_run()
        self.assertEqual(run.trigger, 'manual')
        self.assertEqual(run.operator, '王五')

    def test_auto_quiet_nodes_schedule_recheck(self):
        # 编辑中节点（修改时间 1 分钟前 < 10 分钟静默窗口）：auto 跳过并预约补跑
        editing_dt = SimpleNamespace(
            walk_tree_iter=lambda *a, **k: iter([[{'nodeId': 'n1', 'name': '编辑中.pdf',
                                                   'category': 'DOCUMENT',
                                                   'modifiedTimestamp': _now_ms() - 60_000}]]),
            list_workspaces=lambda: [], close=lambda: None)
        with patch.object(catalog, 'make_dingtalk_client',
                          lambda db, operator_union_id='': editing_dt):
            result = self._run('auto')
        self.assertEqual(result['quiet'], 1)
        self.assertEqual(result['queued'], 0)
        self.assertEqual(self.rechecks, [(self.source_id, 10 * 60 + 60)])
        run = self._last_run()
        self.assertEqual(run.status, 'success')
        self.assertIn('静默', run.message)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncTask).count(), 0)

    def test_manual_ignores_quiet_window(self):
        # 手动同步是明确指令：同样编辑中的节点直接排队，不预约补跑
        with patch.object(catalog, 'make_dingtalk_client',
                          lambda db, operator_union_id='': SimpleNamespace(
                              walk_tree_iter=lambda *a, **k: iter(
                                  [[{'nodeId': 'n1', 'name': '编辑中.pdf',
                                     'category': 'DOCUMENT',
                                     'modifiedTimestamp': _now_ms() - 60_000}]]),
                              list_workspaces=lambda: [], close=lambda: None)):
            result = self._run('manual', '王五')
        self.assertEqual(result['quiet'], 0)
        self.assertEqual(result['queued'], 1)
        self.assertEqual(self.rechecks, [])
        with self.sessions() as db:
            task = db.query(SyncTask).one()
            self.assertEqual((task.trigger, task.operator), ('manual', '王五'))
            self.assertEqual(task.action, 'create')
            doc = db.get(self.doc_cls, _uuid.UUID(task.library_document_id))
            self.assertEqual(doc.status, 'PENDING')

    def test_streamed_walk_persists_batch_before_walk_completes(self):
        # 整树流式编目：第一个目录处理完即落库可见，不等整树遍历结束
        # （「添加知识」弹窗首批秒级关闭的关键）。生成器在消费线程内推进，
        # yield 恢复后可直接查库断言中间状态。
        probe = {'docs_after_first_chunk': None}

        def streamed(*a, **k):
            yield [{'nodeId': 'c1', 'name': '一.pdf', 'category': 'DOCUMENT'},
                   {'nodeId': 'c2', 'name': '二.pdf', 'category': 'DOCUMENT'}]
            with self.sessions() as db:
                probe['docs_after_first_chunk'] = db.query(self.doc_cls).count()
            yield [{'nodeId': 'c3', 'name': '三.pdf', 'category': 'DOCUMENT'}]

        with patch.object(catalog, 'make_dingtalk_client',
                          lambda db, operator_union_id='': SimpleNamespace(
                              walk_tree_iter=streamed,
                              list_workspaces=lambda: [], close=lambda: None)):
            result = self._run('manual')
        self.assertEqual(result['queued'], 3)
        self.assertEqual(probe['docs_after_first_chunk'], 2)
        with self.sessions() as db:
            self.assertEqual(db.query(self.doc_cls).count(), 3)
            self.assertEqual({d.status for d in db.query(self.doc_cls).all()}, {'PENDING'})


class CatalogWhitelistTest(unittest.TestCase):
    """指定文档模式编目：逐节点 get_node 免整树遍历；失败节点跳过；分批落库不丢行。"""

    def setUp(self):
        self.engine, self.sessions = _sqlite_sessions(
            SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask, Setting)
        self.doc_cls = _FullDocStub.build()
        self.doc_cls.__table__.create(self.engine)
        with self.sessions() as db:
            db.add(SyncSource(name='指定文档源', workspace_id='ws-7', root_node_id='r',
                              dataset_id='1', dataset_name='t', enabled=True,
                              node_whitelist='["n1", "n2", "n3"]'))
            db.commit()
            self.source_id = db.query(SyncSource).one().id
        self.walk_calls = []
        self.patches = [
            _patch_session(catalog, self.sessions),
            patch.object(catalog, 'LibraryDocument', self.doc_cls),
            patch.object(catalog, 'get_settings', lambda: SimpleNamespace(
                sync_max_depth=5, sync_max_results_per_page=100, sync_edit_quiet_minutes=0,
                sync_skip_ext_list=[])),
            patch.object(catalog, 'make_dingtalk_client',
                         lambda db, operator_union_id='': self._fake_dt()),
            patch.object(catalog, 'make_library_backend',
                         lambda source: SimpleNamespace(library_id=1, close=lambda: None)),
            patch('app.services.dingtalk_operator.resolve_source_operator_sync',
                  lambda db, source: ('', '测试身份')),
            patch.object(scheduler, 'trigger_batch_once', lambda: None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.engine.dispose()

    def _fake_dt(self):
        from app.services.sync.dingtalk_sync_client import DingTalkError

        def get_node(node_id):
            if node_id == 'n2':
                raise DingTalkError('node not found', status=404)
            return {'node': {'nodeId': node_id, 'name': f'文档-{node_id}',
                             'category': 'DOCUMENT', 'modifiedTimestamp': 1}}

        return SimpleNamespace(
            # 白名单模式必须免整树遍历：walk_tree / walk_tree_iter 一旦被调用即记为违规
            walk_tree=lambda *a, **k: self.walk_calls.append('walk_tree') or [],
            walk_tree_iter=lambda *a, **k: self.walk_calls.append('walk_tree_iter') or iter([]),
            get_node=get_node,
            list_workspaces=lambda: [{'workspaceId': 'ws-7', 'name': '钉钉知识库A'}],
            close=lambda: None)

    def _run(self, trigger='manual', operator='张三'):
        # 清掉上一用例遗留的 running run（批处理未消费完会跳过新一轮编目）
        with self.sessions() as db:
            db.query(SyncRun).filter_by(source_id=self.source_id).delete()
            db.commit()
        return catalog.run_catalog(self.source_id, trigger, operator)

    def test_whitelist_uses_get_node_and_skips_missing(self):
        result = self._run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['queued'], 2)  # n2 获取失败跳过
        self.assertEqual(self.walk_calls, [])  # 未整树遍历
        with self.sessions() as db:
            tasks = db.query(SyncTask).order_by(SyncTask.node_id).all()
            self.assertEqual([t.node_id for t in tasks], ['n1', 'n3'])
            self.assertEqual({t.action for t in tasks}, {'create'})
            docs = db.query(self.doc_cls).all()
            self.assertEqual({d.status for d in docs}, {'PENDING'})
            self.assertEqual({d.source_workspace_name for d in docs}, {'钉钉知识库A'})
            mappings = db.query(SyncDocumentMapping).all()
            self.assertEqual({m.node_id for m in mappings}, {'n1', 'n3'})

    def test_batched_flush_keeps_all_rows(self):
        # 45 篇 > 多个分批窗口（_CATALOG_FLUSH_EVERY=2）：中间多次 commit，
        # 断言无丢行、全部为 PENDING 占位（分批落库供前端陆续感知）
        import json as _json
        big = _json.dumps([f"m{i}" for i in range(45)])
        with self.sessions() as db:
            db.query(SyncSource).filter_by(id=self.source_id).update(
                {'node_whitelist': big})
            db.commit()
        with patch.object(catalog, '_CATALOG_FLUSH_EVERY', 2):
            result = self._run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['queued'], 45)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncTask).count(), 45)
            self.assertEqual(db.query(self.doc_cls).count(), 45)
            self.assertEqual(db.query(SyncDocumentMapping).count(), 45)


if __name__ == '__main__':
    unittest.main()
