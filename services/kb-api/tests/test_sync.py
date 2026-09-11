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

from kb_common.models import SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure
from app.services.sync import engine, runtime
from app.services.sync.dify_sync_client import DifyClient, DifyError


class DifyTests(unittest.TestCase):
    def client(self, handler):
        client = DifyClient('http://dify/v1', 'test')
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_pptx_upload_inherits_parent_child_rules(self):
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
            client.upload_file('dataset', path)
            client.update_file('dataset', 'doc', path)
        for request in requests:
            if request.method == 'POST':
                body = request.content.decode()
                self.assertIn('课程.md', body)
                self.assertIn('流程课程', body)
                self.assertIn('hierarchical_model', body)
                self.assertNotIn('process_rule', body)

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


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.sql = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        for model in (SyncSource, SyncRun, SyncDocumentMapping, SyncLog, SyncFailure):
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
        self.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': '课件.pptx', 'category': 'DOCUMENT'}]
        self.dify = MagicMock()
        self.dify.find_dataset_by_name.return_value = {'id': 'dataset'}
        self.dify.upload_file.return_value = {'document': {'id': 'remote-doc'}, 'batch': 'b'}
        self.dify.update_file.return_value = self.dify.upload_file.return_value
        for target, value in [('make_dingtalk_client', self.dt), ('make_dify_client', self.dify)]:
            p = patch.object(engine, target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(engine.SyncEngine, '_fetch', return_value=(Path('课件.pptx'), 'hash'))
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


if __name__ == '__main__':
    unittest.main()
