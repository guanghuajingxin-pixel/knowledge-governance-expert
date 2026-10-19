"""MinerU 云 SaaS 注册表自愈恢复：服务重启（_JOBS 清空）后按云端 batch 结果重建。

覆盖：注册表 miss + 云端有结果 → 恢复并写回；云端无此 batch → 404；
解析中（云端结果条目为空）→ running 占位（不写回，等结果产出后完整恢复）。
另覆盖同步任务生命周期扩展：文档解析终态 → 关联 running 任务收尾。
"""
import unittest
import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.routes import mineru_saas
from app.services.sync import batch
from kb_common.models import SyncLog, SyncRun, SyncSource, SyncTask


def _cloud_payload(items):
    return {"code": 0, "data": {"extract_result": items}}


class SaaSJobRecoveryTest(unittest.TestCase):
    def setUp(self):
        mineru_saas._JOBS.clear()
        mineru_saas._ZIPS.clear()

    tearDown = setUp

    def _patch_conn(self):
        return patch.object(mineru_saas, '_effective_conn',
                            return_value=("https://mineru.example/api/v4", "sk-test"))

    def test_recover_completed_job_from_cloud(self):
        items = [{"state": "done", "file_name": "手册.pdf",
                  "full_zip_url": "https://cdn.example/x.zip"}]
        # saas_get_job 是协程，用 asyncio 驱动
        import asyncio

        async def run():
            with self._patch_conn(), \
                 patch.object(mineru_saas, '_saas_request',
                              return_value=_cloud_payload(items)), \
                 patch.object(mineru_saas, '_ensure_zip', return_value=b'zip-bytes'):
                return await mineru_saas.saas_get_job("batch-1")

        brief = asyncio.run(run())
        self.assertEqual(brief["status"], "completed")
        self.assertEqual(brief["job_id"], "batch-1")
        # 恢复结果写回注册表：后续 zip_bundle / markdown 产物路径可用
        self.assertIn("batch-1", mineru_saas._JOBS)
        self.assertEqual(mineru_saas._JOBS["batch-1"]["files"][0]["state"], "completed")

    def test_recover_running_job_no_items(self):
        import asyncio

        async def run():
            with self._patch_conn(), \
                 patch.object(mineru_saas, '_saas_request',
                              return_value=_cloud_payload([])):
                return await mineru_saas.saas_get_job("batch-2")

        brief = asyncio.run(run())
        self.assertEqual(brief["status"], "running")
        # 解析中占位不写回注册表：下次查询再走云端（结果产出后完整恢复）
        self.assertNotIn("batch-2", mineru_saas._JOBS)

    def test_cloud_miss_raises_404(self):
        import asyncio

        async def run():
            with self._patch_conn(), \
                 patch.object(mineru_saas, '_saas_request',
                              side_effect=HTTPException(502, "MinerU 云 API 返回 HTTP 404")):
                return await mineru_saas.saas_get_job("gone")

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run())
        self.assertEqual(ctx.exception.status_code, 404)


class SyncTaskLifecycleTest(unittest.TestCase):
    """同步任务生命周期覆盖解析：文档解析终态 → 关联 running 任务收尾。"""

    def setUp(self):
        from tests.test_sync_event_listener import _sqlite_sessions
        self.engine, self.sessions = _sqlite_sessions(SyncSource, SyncRun, SyncTask, SyncLog)
        self.doc_uuid = _uuid.uuid4()
        with self.sessions() as db:
            db.add(SyncSource(name='s', workspace_id='ws', root_node_id='r',
                              dataset_id='1', dataset_name='t', enabled=True))
            db.commit()
            src = db.query(SyncSource).one()
            run = SyncRun(source_id=src.id, trigger='manual', status='running')
            db.add(run)
            db.commit()
            db.add(SyncTask(run_id=run.id, source_id=src.id, name='文档A',
                            library_document_id=str(self.doc_uuid), status='running',
                            started_at=None))
            db.commit()
            self.task_id = db.query(SyncTask).one().id
            self.run_id = run.id

    def tearDown(self):
        self.engine.dispose()

    def _settle(self, doc_status, message=''):
        doc = SimpleNamespace(id=self.doc_uuid, status=doc_status, message=message)
        with self.sessions() as db:
            batch._settle_tasks_for_document(db, doc)
            db.commit()
            return db.get(SyncTask, self.task_id)

    def test_parse_completed_settles_task_success(self):
        t = self._settle('COMPLETED')
        self.assertEqual(t.status, 'success')
        self.assertEqual(t.error, '')
        self.assertIsNotNone(t.finished_at)

    def test_parse_failed_settles_task_failed_with_reason(self):
        t = self._settle('FAILED', 'MinerU 网络错误')
        self.assertEqual(t.status, 'failed')
        self.assertIn('解析失败', t.error)
        self.assertIn('MinerU 网络错误', t.error)

    def test_parse_cancelled_settles_task_failed(self):
        t = self._settle('CANCELLED')
        self.assertEqual(t.status, 'failed')
        self.assertIn('已取消', t.error)

    def test_run_finalized_when_all_tasks_settled(self):
        self._settle('COMPLETED')
        with self.sessions() as db:
            run = db.get(SyncRun, self.run_id)
            self.assertEqual(run.status, 'success')


if __name__ == '__main__':
    unittest.main()
