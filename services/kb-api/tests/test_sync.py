import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kb_common.models import (Setting, SyncSource, SyncRun, SyncDocumentMapping,
                              SyncLog, SyncFailure, SyncTask)
from app.services.sync import engine, runtime


def _library_document_stub():
    """SQLite 测试替身：LibraryDocument 带 PG ARRAY 列，SQLite 无法建表。"""
    import uuid as _uuid
    from sqlalchemy import Column, Integer, String
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.orm import declarative_base

    class _Doc(declarative_base()):
        __tablename__ = 'library_documents'
        id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
        library_id = Column(Integer)
        status = Column(String(20), default='PENDING')

    return _Doc


@contextmanager
def free_lock(*args):
    yield True


def make_fake_settings(**overrides):
    """委托真实 settings 并覆盖指定键；保留 sync_skip_ext_list 等 pydantic 方法。"""
    from kb_common.config import get_settings as real_get_settings
    real = real_get_settings()

    class FakeSettings:
        def __init__(self, real, ov):
            object.__setattr__(self, '_real', real)
            object.__setattr__(self, '_ov', ov)
        def __getattr__(self, name):
            ov = object.__getattribute__(self, '_ov')
            if name in ov:
                return ov[name]
            return getattr(object.__getattribute__(self, '_real'), name)

    return FakeSettings(real, overrides)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask, Setting):
            model.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            self.source = SyncSource(name='test', workspace_id='w', root_node_id='r',
                                     dataset_id='1', dataset_name='target', enabled=True)
            db.add(self.source)
            # 全局钉钉服务账号：引擎运行前必须能解析同步操作人身份
            db.add(Setting(key='dingtalk_operator_union_id', value='union-1'))
            db.commit()
        self.addCleanup(self.sql.dispose)
        self.patches = [patch.object(engine, 'SyncSessionLocal', self.sessions),
                        patch.object(runtime, 'SyncSessionLocal', self.sessions)]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.dt = MagicMock()
        self.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': '课件.pdf', 'category': 'DOCUMENT'}]
        # 最小 fake backend：本地文档库后端方法面（duck-typing dict 返回）
        self.backend = MagicMock()
        self.backend.resolve_dataset.return_value = {'id': 'dataset', 'name': 'target'}
        self.backend.upload_file.return_value = {'document': {'id': 'remote-doc'}, 'batch': ''}
        self.backend.update_file.return_value = self.backend.upload_file.return_value
        for target, value in [('make_dingtalk_client', self.dt), ('make_library_backend', self.backend)]:
            p = patch.object(engine, target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(engine.SyncEngine, '_fetch', return_value=(Path('课件.pdf'), 'hash'))
        p.start(); self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch.object(engine, '_local_storage_dir', return_value=Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)

    def test_failed_upload_then_retry_creates_without_duplicate(self):
        """上传失败保留映射与失败记录；重试成功后清除失败且不产生重复上传。"""
        self.backend.upload_file.side_effect = RuntimeError('目标文档库上传失败')
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['created'], 0)
        with self.sessions() as db:
            mapping = db.query(SyncDocumentMapping).one()
            self.assertIsNone(mapping.document_id)
            self.assertEqual(mapping.status, 'error')
            self.assertEqual(db.query(SyncFailure).count(), 1)
        self.backend.upload_file.side_effect = None
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created'], 1)
        self.assertEqual(self.backend.upload_file.call_count, 2)
        self.assertEqual(self.backend.update_file.call_count, 0)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncFailure).count(), 0)
            self.assertEqual(db.query(SyncDocumentMapping).one().document_id, 'remote-doc')

    def test_unsupported_extension_skipped_without_upload(self):
        """本地文档库白名单（LIBRARY_EXTENSIONS）不支持的格式跳过，历史失败记录保留以便处理。"""
        self.dt.walk_tree.return_value = [
            {'nodeId': 'n-exe', 'name': '安装包.exe', 'category': 'DOCUMENT'},
            {'nodeId': 'n-pdf', 'name': '手册.pdf', 'category': 'DOCUMENT'},
        ]
        with self.sessions() as db:
            db.add(SyncFailure(run_id=0, source_id=self.source.id, node_id='n-exe',
                               name='安装包.exe', error='历史失败'))
            db.commit()
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['failed'], 0)
        # exe 不在文档库白名单内，不应触达上传；pdf 正常上传一次；mapping 只建 pdf 一条
        self.assertEqual(self.backend.upload_file.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncFailure).count(), 1)  # 未成功上传不能清除历史失败
            self.assertEqual(db.query(SyncDocumentMapping).count(), 1)
            self.assertEqual(db.query(SyncDocumentMapping).one().node_id, 'n-pdf')

    def test_pptx_synced_to_local_library(self):
        """pptx 在本地文档库白名单内，正常上传。"""
        self.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': '课件.pptx', 'category': 'DOCUMENT'}]
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(self.backend.upload_file.call_count, 1)

    def test_db_query_failure_does_not_leave_running_record(self):
        def fail(conn, cursor, statement, params, context, many):
            if statement.startswith('SELECT sync_document_mappings.'):
                raise RuntimeError('database schema missing')
        event.listen(self.sql, 'before_cursor_execute', fail)
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'failed')
        with self.sessions() as db:
            run = db.query(SyncRun).one()
            self.assertEqual(run.status, 'failed')
            self.assertIsNotNone(run.finished_at)
            self.assertIn('database schema missing', run.message)

    def test_supervisor_kills_timed_out_process_and_finishes_run(self):
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired('worker', 1)
        with patch.object(runtime, 'source_lock', free_lock), \
             patch.object(runtime.subprocess, 'Popen', return_value=proc), \
             patch.object(runtime, 'kill_process_group') as kill:
            result = runtime.run_sync(self.source.id)
        kill.assert_called_once_with(proc)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('同步超时', result['message'])
        with self.sessions() as db:
            self.assertIsNotNone(db.query(SyncRun).one().finished_at)

    def test_recovery_keeps_active_worker(self):
        with self.sessions() as db:
            db.add(SyncRun(source_id=self.source.id, status='running')); db.commit()
        @contextmanager
        def locks(source_id, namespace):
            yield namespace != runtime.WORKER_LOCK
        with patch.object(runtime, 'source_lock', locks):
            runtime.recover_interrupted_runs()
        with self.sessions() as db:
            self.assertEqual(db.query(SyncRun).one().status, 'running')
        with patch.object(runtime, 'source_lock', free_lock):
            runtime.recover_interrupted_runs()
        with self.sessions() as db:
            self.assertEqual(db.query(SyncRun).one().status, 'failed')


class FetchSourceFormatTests(unittest.TestCase):
    """源文档直传：下载文件按源扩展名落盘并原样保存，不做格式转换。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync_engine = engine.SyncEngine(MagicMock())
        p = patch.object(engine.minio_client, 'upload_bytes')
        p.start(); self.addCleanup(p.stop)

    def fetch(self, node, name, oss_name=''):
        dt = MagicMock()
        dt.download_document.return_value = (b'%PDF-1.4 fake', oss_name)
        return self.sync_engine._fetch(dt, node, name, Path(self.tmp.name), Path('.'))

    def test_download_keeps_source_name(self):
        local, _digest = self.fetch({'nodeId': 'n1', 'extension': 'pdf'}, '杰克安全管理规定.pdf', 'oss/a.pdf')
        self.assertEqual(local.name, '杰克安全管理规定.pdf')
        self.assertEqual(local.read_bytes(), b'%PDF-1.4 fake')

    def test_download_fills_missing_extension_from_oss_name(self):
        local, _digest = self.fetch({'nodeId': 'n2', 'extension': 'pdf'}, '杰克安全管理规定', 'oss/abc123.pdf')
        self.assertEqual(local.name, '杰克安全管理规定.pdf')
        self.assertEqual(local.read_bytes(), b'%PDF-1.4 fake')

    def test_download_fills_missing_extension_from_node_extension(self):
        local, _digest = self.fetch({'nodeId': 'n3', 'extension': 'docx'}, '制度文档', '')
        self.assertEqual(local.name, '制度文档.docx')

    def test_source_file_name_prefers_original_name(self):
        self.assertEqual(engine.SyncEngine._source_file_name('a.pdf', 'pdf', 'x.pdf'), 'a.pdf')
        self.assertEqual(engine.SyncEngine._source_file_name('a', '', ''), 'a')


class RetireImportOnceTests(unittest.TestCase):
    """单次导入源收编：队列清空且全部成功后自动停用源与调度作业。"""

    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask, Setting):
            model.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)

    def tearDown(self):
        self.sql.dispose()

    def _once_source(self, db, **kw):
        defaults = dict(name='单次导入', workspace_id='w', root_node_id='r',
                        dataset_id='1', dataset_name='t', enabled=True,
                        import_once=True, xxl_job_id=99)
        src = SyncSource(**{**defaults, **kw})
        db.add(src)
        db.commit()
        return src

    def test_retire_disables_once_source_when_queue_empty(self):
        from app.services.sync import batch
        with self.sessions() as db:
            src = self._once_source(db)
            with patch('app.services.sync.scheduler.stop_source_job') as stop:
                batch.retire_import_once(db, src.id)
            self.assertFalse(src.enabled)
            stop.assert_called_once_with(99)

    def test_retire_keeps_source_when_tasks_pending(self):
        from app.services.sync import batch
        with self.sessions() as db:
            src = self._once_source(db)
            run = SyncRun(source_id=src.id, status='running')
            db.add(run)
            db.commit()
            db.add(SyncTask(run_id=run.id, source_id=src.id, kind='sync', action='create',
                            node_id='n', name='n', dataset_id='1', dataset_name='t',
                            status='pending'))
            db.commit()
            with patch('app.services.sync.scheduler.stop_source_job') as stop:
                batch.retire_import_once(db, src.id)
            self.assertTrue(src.enabled)
            stop.assert_not_called()

    def test_retire_ignores_periodic_source(self):
        from app.services.sync import batch
        with self.sessions() as db:
            src = self._once_source(db, import_once=False)
            with patch('app.services.sync.scheduler.stop_source_job') as stop:
                batch.retire_import_once(db, src.id)
            self.assertTrue(src.enabled)
            stop.assert_not_called()

    def test_finalize_retires_once_source_on_success_but_not_partial(self):
        from app.services.sync import batch
        # 全部成功 → 收编停用
        with self.sessions() as db:
            src = self._once_source(db)
            run = SyncRun(source_id=src.id, status='running', total=1)
            db.add(run)
            db.commit()
            db.add(SyncTask(run_id=run.id, source_id=src.id, kind='sync', action='create',
                            node_id='n', name='n', dataset_id='1', dataset_name='t',
                            status='success'))
            db.commit()
            with patch('app.services.sync.scheduler.stop_source_job'):
                batch._finalize_run_if_done(db, run.id)
            self.assertEqual(run.status, 'success')
            self.assertFalse(src.enabled)
        # 存在失败 → 保持启用，等 cron 增量重试
        with self.sessions() as db:
            src = self._once_source(db)
            run = SyncRun(source_id=src.id, status='running', total=2, failed_count=1)
            db.add(run)
            db.commit()
            for i, st in enumerate(('success', 'failed')):
                db.add(SyncTask(run_id=run.id, source_id=src.id, kind='sync', action='create',
                                node_id=f'n{i}', name=f'n{i}', dataset_id='1', dataset_name='t',
                                status=st))
            db.commit()
            with patch('app.services.sync.scheduler.stop_source_job') as stop:
                batch._finalize_run_if_done(db, run.id)
            self.assertEqual(run.status, 'partial')
            self.assertTrue(src.enabled)
            stop.assert_not_called()


class BatchDeleteTasksTests(unittest.TestCase):
    """同步队列批量清理/移出：非处理中状态均可移出；未同步完成的联动排除自动同步。"""

    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask, Setting):
            model.__table__.create(self.sql)
        self.doc_cls = _library_document_stub()
        self.doc_cls.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)

    def tearDown(self):
        self.sql.dispose()

    def _source(self, db):
        src = SyncSource(name='s', workspace_id='w', root_node_id='r',
                         dataset_id='1', dataset_name='t', enabled=True)
        db.add(src)
        db.commit()
        return src

    def _pending_task(self, db, src, node_id='n1', status='pending',
                      mapping_status='pending', doc_status='PENDING'):
        """构造一条任务及其映射/预建文档，返回 (task, mapping, doc_id)。"""
        run = db.query(SyncRun).filter_by(source_id=src.id, status='running').first()
        if run is None:
            run = SyncRun(source_id=src.id, status='running')
            db.add(run)
            db.commit()
        doc_id = None
        if doc_status is not None:
            doc = self.doc_cls(library_id=1, status=doc_status)
            db.add(doc)
            db.commit()
            doc_id = str(doc.id)
        mapping = None
        if mapping_status is not None:
            mapping = SyncDocumentMapping(source_id=src.id, node_id=node_id, name='doc',
                                           category='', status=mapping_status, document_id=doc_id)
            db.add(mapping)
            db.commit()
        task = SyncTask(run_id=run.id, source_id=src.id, kind='sync', action='create',
                        node_id=node_id, name='doc', dataset_id='1', dataset_name='t',
                        status=status)
        db.add(task)
        db.commit()
        return task, mapping, doc_id

    def test_remove_pending_task_excludes_mapping_and_placeholder_doc(self):
        from app.routes.sync_route import batch_delete_tasks
        from app.schemas import SyncTaskBatchIn
        import uuid as _uuid
        with self.sessions() as db:
            src = self._source(db)
            task, mapping, doc_id = self._pending_task(db, src)
            run_id = task.run_id
            with patch('app.routes.sync_route.LibraryDocument', self.doc_cls):
                res = batch_delete_tasks(SyncTaskBatchIn(ids=[task.id]), db)
            self.assertEqual(res['removed'], 1)
            self.assertEqual(res['excluded'], 1)
            self.assertIsNone(db.get(SyncTask, task.id))
            self.assertFalse(mapping.enabled)              # 排除自动同步，防 cron 重建
            self.assertIsNone(db.get(self.doc_cls, _uuid.UUID(doc_id)))
            # run 已无未完成任务 → 立即收尾，不留 running 卡住 cron 编目
            run = db.get(SyncRun, run_id)
            self.assertEqual(run.status, 'success')

    def test_remove_success_task_keeps_mapping_and_doc(self):
        from app.routes.sync_route import batch_delete_tasks
        from app.schemas import SyncTaskBatchIn
        import uuid as _uuid
        with self.sessions() as db:
            src = self._source(db)
            task, mapping, doc_id = self._pending_task(
                db, src, status='success', mapping_status='synced', doc_status='COMPLETED')
            with patch('app.routes.sync_route.LibraryDocument', self.doc_cls):
                res = batch_delete_tasks(SyncTaskBatchIn(ids=[task.id]), db)
            self.assertEqual(res['removed'], 1)
            self.assertEqual(res['excluded'], 0)
            self.assertTrue(mapping.enabled)               # 已同步成果不受影响
            self.assertIsNotNone(db.get(self.doc_cls, _uuid.UUID(doc_id)))

    def test_running_task_skipped(self):
        from app.routes.sync_route import batch_delete_tasks
        from app.schemas import SyncTaskBatchIn
        with self.sessions() as db:
            src = self._source(db)
            task, _, _ = self._pending_task(db, src, status='running',
                                             mapping_status=None, doc_status=None)
            with patch('app.routes.sync_route.LibraryDocument', self.doc_cls):
                res = batch_delete_tasks(SyncTaskBatchIn(ids=[task.id]), db)
            self.assertEqual(res['removed'], 0)
            self.assertEqual(res['skipped'], 1)
            self.assertIsNotNone(db.get(SyncTask, task.id))


class SyncRunStartedAtTests(unittest.TestCase):
    """回归：SyncRun.started_at 必须与看门狗同基准（应用本地时间）。

    此前仅 server_default=func.now()（Docker PG 会话时区=UTC），与 runtime
    看门狗的本地 datetime.now() 相差 8 小时：batch run 创建后首轮扫描即被判
    stale 误杀，任务全部标记「批处理长时间未推进」失败。
    """

    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool,
                                 connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncTask):
            model.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            db.add(SyncSource(name='t', workspace_id='w', root_node_id='r',
                              dataset_id='1', dataset_name='t', enabled=True))
            db.commit()
        self.addCleanup(self.sql.dispose)

    def test_started_at_uses_local_time_not_stale_on_create(self):
        from datetime import datetime as dt, timedelta
        with self.sessions() as db:
            run = SyncRun(source_id=1, status='running')
            db.add(run)
            db.commit()
            self.assertIsNotNone(run.started_at)
            # 应用侧默认值与本地 now 差值应在秒级（UTC 基准时差数小时）
            drift = abs((dt.now() - run.started_at).total_seconds())
            self.assertLess(drift, 300)
            # 看门狗口径（runtime.recover_interrupted_runs）：新建 run 不得判 stale
            stale_before = dt.now() - timedelta(seconds=21600)
            self.assertGreaterEqual(run.started_at, stale_before)


class BatchRefreshCapTests(unittest.TestCase):
    """回归：批处理 (b) refresh 阶段每轮限量刷新 PARSING 文档。

    僵尸 PARSING 文档（进程崩溃遗留）可能积压数百篇；此前全量刷新会让
    tick 长时间不返回（实测 293 篇 >150s），任务认领被饿死、新任务永远 pending。
    """

    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool,
                                 connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask):
            model.__table__.create(self.sql)
        self.doc_cls = _library_document_stub()
        self.doc_cls.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            db.add(SyncSource(name='t', workspace_id='w', root_node_id='r',
                              dataset_id='1', dataset_name='t', enabled=True))
            db.commit()
        self.addCleanup(self.sql.dispose)

    def test_refresh_caps_parsing_docs_per_tick(self):
        from app.services.sync import batch
        seen = {}

        async def fake_parsings(pairs):
            seen['count'] = len(pairs)

        with self.sessions() as db:
            # 20 篇僵尸 PARSING 文档（带同步映射），超过单轮限量 15
            for i in range(20):
                doc = self.doc_cls(library_id=1, status='PARSING')
                db.add(doc)
                db.flush()
                db.add(SyncDocumentMapping(source_id=1, node_id=f'n{i}', name=f'd{i}',
                                           category='', status='synced',
                                           document_id=str(doc.id)))
            db.commit()
            with patch.object(batch, 'LibraryDocument', self.doc_cls), \
                 patch.object(batch, '_refresh_parsings', fake_parsings):
                batch._refresh_parsing_documents(db)
            self.assertEqual(seen.get('count'), batch._REFRESH_DOCS_PER_TICK)


if __name__ == '__main__':
    unittest.main()
