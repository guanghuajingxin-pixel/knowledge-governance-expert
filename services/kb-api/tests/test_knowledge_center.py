"""知识中心路由单元测试（mock session + 假 MinIO 模块，不依赖真实基础设施）。

当前覆盖：source-documents 批量删除 —— MinIO 文档目录整删（原件 + parsed.md + images/）、
PENDING 占位跳过清理、解析中拒绝整批、缺文档拒绝整批、重复 ID 去重；
batch-delete-all —— 按筛选范围整删（解析中除外）、空范围直接返回。
"""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.routes import knowledge_center as kc


def _doc(status="COMPLETED", storage_path=None, name="产品手册.pdf"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, status=status, storage_path=storage_path,
                           library_id=7)


def _session_with(docs):
    """首次 execute 返回文档查询结果，其余（同步任务 UPDATE）返回占位对象。"""
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: docs))
    return SimpleNamespace(execute=AsyncMock(side_effect=[result, Mock(), Mock()]),
                           delete=AsyncMock(), commit=AsyncMock())


def _fake_minio(delete_prefix):
    """函数内延迟导入的 minio_client 用 sys.modules + 包属性双保险替换，避免真实连接。"""
    import sys
    import types
    import kb_common.clients as clients_pkg
    fake = types.ModuleType('kb_common.clients.minio_client')
    fake.RAW = 'raw-docs'
    fake.delete_prefix = delete_prefix
    return (patch.dict(sys.modules, {'kb_common.clients.minio_client': fake}),
            patch.object(clients_pkg, 'minio_client', fake, create=True))


class BatchDeleteSourceDocumentsTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_delete_removes_minio_doc_dir(self):
        """删除时按文档目录整删 MinIO 对象（原件 + parsed.md + images/），并提交事务。"""
        d1 = _doc(storage_path='document-libraries/7/aaa/doc.pdf')
        d2 = _doc(storage_path='document-libraries/7/bbb/doc.docx')
        s = _session_with([d1, d2])
        dp = Mock(return_value=3)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            res = await kc.batch_delete_source_documents(
                kc.SourceDocBatchDeleteIn(ids=[str(d1.id), str(d2.id)]),
                u=SimpleNamespace(username='u'), s=s)
        self.assertTrue(res['ok'])
        self.assertEqual(res['deleted'], 2)
        self.assertEqual(res['storage_objects'], 6)
        prefixes = [c.args[1] for c in dp.call_args_list]
        self.assertEqual(prefixes, ['document-libraries/7/aaa/', 'document-libraries/7/bbb/'])
        self.assertEqual(s.delete.await_count, 2)
        s.commit.assert_awaited_once()

    async def test_pending_placeholder_without_storage_skips_minio(self):
        """PENDING 占位（storage_path 为空，原件未落 MinIO）跳过清理，仅删记录。"""
        d = _doc(status='PENDING', storage_path='')
        s = _session_with([d])
        dp = Mock(return_value=0)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            res = await kc.batch_delete_source_documents(
                kc.SourceDocBatchDeleteIn(ids=[str(d.id)]),
                u=SimpleNamespace(username='u'), s=s)
        dp.assert_not_called()
        self.assertEqual(res['deleted'], 1)
        self.assertEqual(res['storage_objects'], 0)
        s.delete.assert_awaited_once_with(d)
        s.commit.assert_awaited_once()

    async def test_parsing_doc_rejects_whole_batch(self):
        """解析中的文档拒绝整批删除（避免边解析边删产生脏数据）。"""
        d1 = _doc(name='已解析.pdf')
        d2 = _doc(status='PARSING', name='解析中.pdf')
        s = _session_with([d1, d2])
        with self.assertRaises(HTTPException) as raised:
            await kc.batch_delete_source_documents(
                kc.SourceDocBatchDeleteIn(ids=[str(d1.id), str(d2.id)]),
                u=SimpleNamespace(username='u'), s=s)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn('解析中.pdf', raised.exception.detail)
        s.commit.assert_not_awaited()

    async def test_missing_doc_rejects_batch(self):
        """任一 ID 不存在则整批不删（404）。"""
        d = _doc()
        s = _session_with([d])
        with self.assertRaises(HTTPException) as raised:
            await kc.batch_delete_source_documents(
                kc.SourceDocBatchDeleteIn(ids=[str(d.id), str(uuid.uuid4())]),
                u=SimpleNamespace(username='u'), s=s)
        self.assertEqual(raised.exception.status_code, 404)
        s.commit.assert_not_awaited()

    async def test_duplicate_ids_deduped(self):
        """重复 ID 去重，避免重复执行 MinIO 删除与记录删除。"""
        d = _doc(storage_path='document-libraries/7/aaa/doc.pdf')
        s = _session_with([d])
        dp = Mock(return_value=2)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            res = await kc.batch_delete_source_documents(
                kc.SourceDocBatchDeleteIn(ids=[str(d.id), str(d.id)]),
                u=SimpleNamespace(username='u'), s=s)
        self.assertEqual(res['deleted'], 1)
        dp.assert_called_once()
        s.delete.assert_awaited_once_with(d)

    def test_empty_and_oversized_ids_rejected(self):
        """入参校验：空列表与超过 100 个 ID 均拒绝。"""
        with self.assertRaises(Exception):
            kc.SourceDocBatchDeleteIn(ids=[])
        with self.assertRaises(Exception):
            kc.SourceDocBatchDeleteIn(ids=[str(uuid.uuid4()) for _ in range(101)])


class BatchDeleteAllSourceDocumentsTests(unittest.IsolatedAsyncioTestCase):
    """删除全部：当前筛选命中的全部知识（含未翻到的页），解析中的除外。"""

    def _session(self, docs, excluded=0):
        """execute 序列：文档查询 → 解析中计数 → 同步任务 UPDATE。"""
        docs_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: docs))
        count_result = SimpleNamespace(scalar_one=lambda: excluded)
        return SimpleNamespace(
            execute=AsyncMock(side_effect=[docs_result, count_result, Mock()]),
            delete=AsyncMock(), commit=AsyncMock())

    async def test_delete_all_removes_minio_and_reports_excluded(self):
        """按文档目录整删 MinIO 并提交；解析中的计数体现在 message。"""
        d1 = _doc(storage_path='document-libraries/7/aaa/doc.pdf')
        d2 = _doc(storage_path='document-libraries/7/bbb/doc.docx')
        s = self._session([d1, d2], excluded=1)
        dp = Mock(return_value=3)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            res = await kc.batch_delete_all_source_documents(
                search='手册', source='local', tag=None,
                u=SimpleNamespace(username='u'), s=s)
        self.assertTrue(res['ok'])
        self.assertEqual(res['deleted'], 2)
        self.assertEqual(res['excluded'], 1)
        self.assertEqual(res['storage_objects'], 6)
        self.assertIn('已删除 2 项知识', res['message'])
        self.assertIn('1 项解析/训练中的知识未删除', res['message'])
        prefixes = [c.args[1] for c in dp.call_args_list]
        self.assertEqual(prefixes, ['document-libraries/7/aaa/', 'document-libraries/7/bbb/'])
        self.assertEqual(s.delete.await_count, 2)
        s.commit.assert_awaited_once()

    async def test_delete_all_passes_filter_scope(self):
        """筛选参数（来源/关键词）传入查询条件，与列表口径一致。"""
        d = _doc(storage_path='document-libraries/7/aaa/doc.pdf')
        s = self._session([d])
        dp = Mock(return_value=0)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            await kc.batch_delete_all_source_documents(
                search='手册', source='dingtalk', tag='产品',
                u=SimpleNamespace(username='u'), s=s)
        stmt = s.execute.await_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn("library_type = 'document'", compiled)
        self.assertIn("source = 'dingtalk'", compiled)
        self.assertIn('手册', compiled)
        self.assertIn('产品', compiled)
        self.assertIn("status NOT IN ('PARSING', 'TRAINING')", compiled)
        self.assertNotIn('LIMIT', compiled)  # 缺省 limit 不限制，一次删完

    async def test_delete_all_limit_batches_query(self):
        """传 limit 时单批最多删除指定条数（前端分批循环用）。"""
        d = _doc(storage_path='document-libraries/7/aaa/doc.pdf')
        s = self._session([d])
        dp = Mock(return_value=0)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            await kc.batch_delete_all_source_documents(
                search=None, source=None, tag=None, limit=50,
                u=SimpleNamespace(username='u'), s=s)
        stmt = s.execute.await_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('LIMIT 50', compiled)

    async def test_delete_all_empty_range_returns_early(self):
        """范围内无可删除知识时直接返回，不删任何对象、不提交。"""
        s = self._session([])
        dp = Mock(return_value=0)
        m1, m2 = _fake_minio(dp)
        with m1, m2:
            res = await kc.batch_delete_all_source_documents(
                search=None, source=None, tag=None,
                u=SimpleNamespace(username='u'), s=s)
        self.assertEqual(res['deleted'], 0)
        self.assertEqual(res['excluded'], 0)
        self.assertIn('没有可删除', res['message'])
        s.execute.assert_awaited_once()
        dp.assert_not_called()
        s.delete.assert_not_awaited()
        s.commit.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
