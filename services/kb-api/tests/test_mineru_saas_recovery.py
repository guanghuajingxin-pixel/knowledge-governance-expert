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


class OrphanSettleClaimExemptionTest(unittest.TestCase):
    """孤儿收尾认领豁免：文档终态早于任务认领（旧失败残留）不收尾，
    避免重试任务刚认领就被旧状态打死（重试永远失败的死循环）。"""

    def setUp(self):
        from datetime import datetime as _dt
        from tests.test_sync_event_listener import _sqlite_sessions
        from sqlalchemy import Column, DateTime, String, Text
        from sqlalchemy.dialects.postgresql import UUID
        from sqlalchemy.orm import declarative_base

        self._dt = _dt
        self.engine, self.sessions = _sqlite_sessions(SyncSource, SyncRun, SyncTask, SyncLog)
        # LibraryDocument 带 PG ARRAY 列，sqlite 建不了原表：stub 只建 settle 用到的列
        class _StubDoc(declarative_base()):
            __tablename__ = 'library_documents'
            id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
            status = Column(String(20), default='PENDING')
            message = Column(Text, default='')
            updated_at = Column(DateTime)
        _StubDoc.__table__.create(self.engine)
        self._stub_doc_cls = _StubDoc
        patches = [patch.object(batch, 'LibraryDocument', _StubDoc),
                   patch.object(batch, 'SyncSessionLocal', self.sessions)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.doc_uuid = _uuid.uuid4()
        with self.sessions() as db:
            db.add(SyncSource(name='s', workspace_id='ws', root_node_id='r',
                              dataset_id='1', dataset_name='t', enabled=True))
            db.commit()
            src = db.query(SyncSource).one()
            run = SyncRun(source_id=src.id, trigger='manual', status='running')
            db.add(run)
            db.commit()
            db.add(SyncTask(run_id=run.id, source_id=src.id, name='表格.able',
                            library_document_id=str(self.doc_uuid), status='running',
                            started_at=None))
            db.commit()
            self.task_id = db.query(SyncTask).one().id

    def tearDown(self):
        self.engine.dispose()

    def _add_doc(self, status, updated_at, message=''):
        with self.sessions() as db:
            db.add(self._stub_doc_cls(id=self.doc_uuid, status=status,
                                      message=message, updated_at=updated_at))
            db.commit()

    def _claim(self, started_at):
        with self.sessions() as db:
            t = db.get(SyncTask, self.task_id)
            t.started_at = started_at
            db.commit()

    def test_stale_doc_failed_before_claim_not_settled(self):
        """文档 FAILED 终态早于任务认领（重试场景旧残留）：不收尾，任务留待消费主路径。"""
        self._claim(self._dt(2026, 10, 19, 21, 20, 0))
        self._add_doc('FAILED', self._dt(2026, 10, 19, 19, 7, 36),
                      message='同步失败: ExportError: 找不到 dws 命令')
        self.assertEqual(batch._settle_orphaned_running_tasks(), 0)
        with self.sessions() as db:
            task = db.get(SyncTask, self.task_id)
            self.assertEqual(task.status, 'running')
            self.assertEqual(task.error, '')

    def test_doc_advanced_after_claim_settles(self):
        """认领后文档被外部（前端 refresh）推进 COMPLETED：正常兜底收尾。"""
        self._claim(self._dt(2026, 10, 19, 21, 20, 0))
        self._add_doc('COMPLETED', self._dt(2026, 10, 19, 21, 21, 5))
        self.assertEqual(batch._settle_orphaned_running_tasks(), 1)
        with self.sessions() as db:
            self.assertEqual(db.get(SyncTask, self.task_id).status, 'success')

    def test_started_at_missing_falls_back_to_settle(self):
        """存量任务 started_at 缺失：维持旧行为兜底收尾，防孤儿卡 30 分钟回收窗。"""
        self._add_doc('FAILED', self._dt(2026, 10, 19, 19, 7, 36), message='解析失败')
        self.assertEqual(batch._settle_orphaned_running_tasks(), 1)
        with self.sessions() as db:
            self.assertEqual(db.get(SyncTask, self.task_id).status, 'failed')


if __name__ == '__main__':
    unittest.main()
