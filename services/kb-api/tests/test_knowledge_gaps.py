import io
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from kb_common.models import User, KnowledgeBase, Directory, Document
from app.routes import knowledge_gaps as gaps


class CoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_permission_counts_deleted_and_nested_directories(self):
        engine = create_engine('sqlite://')
        for model in (User, KnowledgeBase, Directory, Document):
            model.__table__.create(engine)
        with Session(engine) as session:
            user = User(username='editor', password_hash='x', role='editor')
            other = User(username='other', password_hash='x')
            session.add_all([user, other]); session.flush()
            a = KnowledgeBase(name='可见', kb_type='DOCUMENT', owner_id=user.id, es_index_name='a')
            b = KnowledgeBase(name='不可见', kb_type='DOCUMENT', owner_id=other.id, es_index_name='b')
            session.add_all([a,b]); session.flush()
            parent = Directory(name='父目录', kb_id=a.id)
            secret = Directory(name='秘密', kb_id=b.id)
            session.add_all([parent,secret]); session.flush()
            child = Directory(name='子目录', kb_id=a.id, parent_id=parent.id)
            session.add(child); session.flush()
            for d, deleted in [(child,False),(child,True),(parent,True)]:
                session.add(Document(kb_id=a.id, directory_id=d.id, filename='a', original_filename='a',
                                     file_type='txt', storage_path='a', is_deleted=deleted))
            session.commit()
            wrapper = SimpleNamespace(execute=AsyncMock(side_effect=session.execute))
            items, _, _ = await gaps.inventory(wrapper, user)
            self.assertEqual({r['directory_path']: r['document_count'] for r in items}, {'父目录':0,'父目录/子目录':1})
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'empty')),1)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'has')),1)
            # 数量区间过滤：父目录(文档0/子文件夹1)、子目录(文档1/子文件夹0)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'all', '0')),1)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'all', '1-9')),1)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'all', '100+')),0)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'all', None, '0')),1)
            self.assertEqual(len(gaps.filtered(items, True, a.id, None, 'all', None, '1-9')),1)
            user.role='admin'
            items, _, _ = await gaps.inventory(wrapper,user)
            self.assertEqual(len(items),3)
        engine.dispose()

    async def test_import_is_atomic_and_rejects_inaccessible_directory(self):
        key = str(uuid.uuid4())
        directory = SimpleNamespace(id=uuid.UUID(key), knowledge_owner='旧Owner')
        data = f'目录ID,知识Owner\n{key},新Owner\n{uuid.uuid4()},秘密\n'
        session = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        with patch.object(gaps, 'inventory', AsyncMock(return_value=([],[directory],[]))):
            with self.assertRaises(HTTPException):
                await gaps.import_owners(UploadFile(filename='a.csv', file=io.BytesIO(data.encode())), None, session)
        self.assertEqual(directory.knowledge_owner,'旧Owner')
        session.commit.assert_not_awaited()

    async def test_xlsx_import_matches_path(self):
        from openpyxl import Workbook
        book=Workbook(); book.active.append(['知识库','目录路径','知识Owner'])
        book.active.append(['库','父/子','张三'])
        output=io.BytesIO(); book.save(output); output.seek(0)
        key=uuid.uuid4()
        directory=SimpleNamespace(id=key,knowledge_owner='')
        items=[dict(directory_id=str(key),kb_name='库',directory_path='父/子')]
        session=SimpleNamespace(commit=AsyncMock(), execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
        with patch.object(gaps,'inventory',AsyncMock(return_value=(items,[directory],[]))):
            result=await gaps.import_owners(UploadFile(filename='a.xlsx',file=output),None,session)
        self.assertEqual(result,{'updated':1})
        self.assertEqual(directory.knowledge_owner,'张三')

    def test_export_formula_injection_and_bom(self):
        response=gaps.csv_response([['知识Owner'],['=HYPERLINK("x")']], 'a.csv')
        self.assertTrue(response.body.startswith(b'\xef\xbb\xbf'))
        self.assertIn("'=HYPERLINK", response.body.decode('utf-8-sig'))


class _SessionCtx:
    """把同步构造的假 session 适配成 async with SessionLocal() 形态。"""
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _fake_session_factory(session):
    """patch SessionLocal 用：SessionLocal() 调用后返回 async with 兼容对象。"""
    return lambda: _SessionCtx(session)


class NightlyGapRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_all_iterates_enabled_sources_and_skips_running(self):
        sources = [SimpleNamespace(id=1, external_id='kb-a'),
                   SimpleNamespace(id=2, external_id='kb-b')]
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: sources))
        session = SimpleNamespace(execute=AsyncMock(return_value=result))
        gaps._refresh_state.clear()
        gaps._refresh_state['kb-a'] = {'running': True}  # 手动刷新中 → 跳过

        with patch('kb_common.clients.dingtalk_client.sync_runtime_config', AsyncMock()), \
             patch('kb_common.clients.dingtalk_client.is_configured', lambda: True), \
             patch('kb_common.database.SessionLocal', _fake_session_factory(session)), \
             patch.object(gaps, '_refresh_dingtalk_folders_task', AsyncMock()) as task:
            await gaps._refresh_all_gap_snapshots('daily')
        # 只刷新未在跑的 kb-b（id=2）
        task.assert_awaited_once_with(2)

    async def test_refresh_all_skips_when_dingtalk_not_configured(self):
        with patch('kb_common.clients.dingtalk_client.sync_runtime_config', AsyncMock()), \
             patch('kb_common.clients.dingtalk_client.is_configured', lambda: False), \
             patch.object(gaps, '_refresh_dingtalk_folders_task', AsyncMock()) as task:
            await gaps._refresh_all_gap_snapshots('daily')
        task.assert_not_awaited()

    async def test_snapshots_stale_by_latest_fetched_at(self):
        from datetime import datetime, timedelta
        fresh = datetime.now()
        stale = fresh - timedelta(days=1)

        async def check(latest):
            session = SimpleNamespace(scalar=AsyncMock(return_value=latest))
            with patch('kb_common.database.SessionLocal', _fake_session_factory(session)):
                return await gaps._gap_snapshots_stale()

        self.assertFalse(await check(fresh))
        self.assertTrue(await check(stale))
        self.assertTrue(await check(None))
