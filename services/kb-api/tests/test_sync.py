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


if __name__ == '__main__':
    unittest.main()
