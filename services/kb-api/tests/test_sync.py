import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile
from contextlib import contextmanager

import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kb_common.models import SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask
from app.services.sync import engine, runtime
from app.services.sync.dify_sync_client import DifyClient, DifyError


class DifyTests(unittest.TestCase):
    def client(self, handler):
        client = DifyClient('http://dify/v1', 'test')
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_pptx_upload_keeps_source_format(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == 'GET':
                return httpx.Response(200, json={'doc_form': 'hierarchical_model', 'document_count': 1,
                                                'indexing_technique': 'high_quality'})
            return httpx.Response(200, json={'document': {'id': 'doc'}, 'batch': 'batch'})
        client = self.client(handler)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '课程.pptx'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('ppt/slides/slide1.xml', '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>流程课程</a:t></a:p>')
            source = path.read_bytes()
            client.upload_file('dataset', path)
            client.update_file('dataset', 'doc', path)
        posts = [r for r in requests if r.method == 'POST']
        self.assertEqual(len(posts), 2)
        for request in posts:
            body = request.content
            text = body.decode('utf-8', 'replace')
            self.assertIn('filename="课程.pptx"', text)
            self.assertIn(source, body)
            self.assertIn('hierarchical_model', text)
            self.assertNotIn('process_rule', text)
            self.assertNotIn('课程.md', text)

    def test_pdf_upload_passthrough(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == 'GET':
                return httpx.Response(200, json={'doc_form': 'text_model', 'document_count': 1,
                                                'indexing_technique': 'high_quality'})
            return httpx.Response(200, json={'document': {'id': 'doc'}, 'batch': 'batch'})
        client = self.client(handler)
        source = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '杰克安全管理规定.pdf'
            path.write_bytes(source)
            client.upload_file('dataset', path)
        posts = [r for r in requests if r.method == 'POST']
        self.assertEqual(len(posts), 1)
        body = posts[0].content
        text = body.decode('utf-8', 'replace')
        self.assertIn('filename="杰克安全管理规定.pdf"', text)
        self.assertIn('application/pdf', text)
        self.assertIn(source, body)

    def test_new_text_dataset_has_default_rule(self):
        client = self.client(lambda r: httpx.Response(200, json={'document_count': 0}))
        self.assertEqual(client._file_payload('d', 'Chinese')['process_rule'], {'mode': 'automatic'})

    def test_indexing_error_is_failure(self):
        client = self.client(lambda r: httpx.Response(200, json={'data': [
            {'indexing_status': 'error', 'error': 'embedding quota exceeded'}]}))
        with self.assertRaisesRegex(DifyError, 'embedding quota exceeded'):
            client.wait_indexing('d', 'b')

    def test_indexing_timeout_is_failure(self):
        client = self.client(lambda r: httpx.Response(200, json={}))
        with self.assertRaisesRegex(DifyError, '超时'):
            client.wait_indexing('d', 'b', timeout=0)

    def test_empty_indexing_response_is_failure(self):
        client = self.client(lambda r: httpx.Response(200, json={'data': []}))
        with self.assertRaisesRegex(DifyError, '未返回'):
            client.wait_indexing('d', 'b')


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
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure, SyncTask):
            model.__table__.create(self.sql)
        self.sessions = sessionmaker(bind=self.sql, expire_on_commit=False)
        with self.sessions() as db:
            self.source = SyncSource(name='test', workspace_id='w', root_node_id='r', dify_dataset_name='target', enabled=True)
            db.add(self.source); db.commit()
        self.addCleanup(self.sql.dispose)
        self.patches = [patch.object(engine, 'SyncSessionLocal', self.sessions),
                        patch.object(runtime, 'SyncSessionLocal', self.sessions)]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.dt = MagicMock()
        self.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': '课件.pdf', 'category': 'DOCUMENT'}]
        self.dify = MagicMock()
        self.dify.resolve_dataset.return_value = {'id': 'dataset', 'name': 'target', 'runtime_mode': 'general'}
        self.dify.upload_file.return_value = {'document': {'id': 'remote-doc'}, 'batch': 'b'}
        self.dify.update_file.return_value = self.dify.upload_file.return_value
        for target, value in [('make_dingtalk_client', self.dt), ('make_backend', self.dify)]:
            p = patch.object(engine, target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(engine.SyncEngine, '_fetch', return_value=(Path('课件.pdf'), 'hash'))
        p.start(); self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch.object(engine, '_local_storage_dir', return_value=Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)

    def test_failed_index_preserves_id_then_updates_without_duplicate(self):
        self.dify.wait_indexing.side_effect = DifyError('索引超时')
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['created'], 0)
        with self.sessions() as db:
            mapping = db.query(SyncDocumentMapping).one()
            self.assertEqual(mapping.dify_document_id, 'remote-doc')
            self.assertEqual(mapping.status, 'error')
            self.assertEqual(db.query(SyncFailure).count(), 1)
        self.dify.wait_indexing.side_effect = None
        self.dify.wait_indexing.return_value = 'completed'
        result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.dify.upload_file.call_count, 1)
        self.assertEqual(self.dify.update_file.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncFailure).count(), 0)

    def test_unsupported_extension_skipped_without_upload(self):
        """普通库内置 ETL 不支持的格式跳过，历史失败记录保留以便处理。"""
        self.dt.walk_tree.return_value = [
            {'nodeId': 'n-pptx', 'name': '课件.pptx', 'category': 'DOCUMENT'},
            {'nodeId': 'n-pdf', 'name': '手册.pdf', 'category': 'DOCUMENT'},
        ]
        with self.sessions() as db:
            db.add(SyncFailure(run_id=0, source_id=self.source.id, node_id='n-pptx',
                               name='课件.pptx', error='历史失败'))
            db.commit()
        # 固定为内置 ETL，避免测试依赖环境里的 DIFY_ETL_TYPE 配置
        with patch.object(engine, 'get_settings', return_value=make_fake_settings(dify_etl_type='dify')):
            result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['failed'], 0)
        # pptx 不应触达 Dify 上传；pdf 正常上传一次；mapping 只建 pdf 一条
        self.assertEqual(self.dify.upload_file.call_count, 1)
        with self.sessions() as db:
            self.assertEqual(db.query(SyncFailure).count(), 1)  # 未成功上传不能清除历史失败
            self.assertEqual(db.query(SyncDocumentMapping).count(), 1)
            self.assertEqual(db.query(SyncDocumentMapping).one().node_id, 'n-pdf')

    def test_pptx_synced_when_dify_runs_unstructured_etl(self):
        """Dify 配置 ETL_TYPE=Unstructured 时，pptx 不再被白名单跳过，正常上传。"""
        fake = make_fake_settings(dify_etl_type='Unstructured')
        self.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': '课件.pptx', 'category': 'DOCUMENT'}]
        with patch.object(engine, 'get_settings', return_value=fake):
            result = engine.SyncEngine(self.source).run()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(self.dify.upload_file.call_count, 1)

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
