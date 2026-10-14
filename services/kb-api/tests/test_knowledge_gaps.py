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


class LinkFolderRowTests(unittest.IsolatedAsyncioTestCase):
    """快捷方式链接（.dlink）单独成行：不计父文档数、不递归、带 is_link 标记。"""

    async def test_walk_dlink_rows(self):
        from kb_common.clients import dingtalk_client
        seen_parents = []

        async def fake_list_nodes(parent_id, operator_union_id=None):
            seen_parents.append(parent_id)
            if parent_id == 'root':
                return [
                    {'nodeId': 'sub', 'name': '子目录', 'type': 'FOLDER'},
                    {'nodeId': 'lnk1', 'name': '架构.dlink', 'type': 'FILE', 'extension': 'dlink'},
                    {'nodeId': 'lnk2', 'name': '引用', 'type': 'FOLDER', 'extension': 'dlink'},
                    {'nodeId': 'doc', 'name': '说明.adoc', 'type': 'FILE', 'extension': 'adoc'},
                ]
            return []

        with patch.object(dingtalk_client, 'list_nodes', fake_list_nodes):
            rows = await dingtalk_client.walk_workspace_folders('root')
        by_path = {r['path']: r for r in rows}
        # .dlink 不计入父文件夹文档数（只剩 1 篇 adoc），FILE/FOLDER 两种类型均成链接行
        self.assertEqual(by_path['']['document_count'], 1)
        self.assertTrue(by_path['架构.dlink']['is_link'])
        self.assertTrue(by_path['引用']['is_link'])
        self.assertEqual(by_path['架构.dlink']['document_count'], 0)
        self.assertNotIn('is_link', by_path['子目录'])
        # 链接不递归：其子节点不会被列出
        self.assertNotIn('lnk1', seen_parents)
        self.assertNotIn('lnk2', seen_parents)

    async def test_dingtalk_rows_expose_link_flag(self):
        source = SimpleNamespace(external_id='kb-x', name='库', config={})
        stat = SimpleNamespace(node_id='n1', path='A/架构.dlink', owner='张三',
                               document_count=0, is_link=True)
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [stat]))
        session = SimpleNamespace(execute=AsyncMock(return_value=result))
        rows = await gaps.dingtalk_folder_rows(session, source)
        self.assertTrue(rows[0]['is_link'])
        self.assertEqual(rows[0]['directory_path'], 'A/架构.dlink')

    async def test_notify_rejects_link_row(self):
        src = SimpleNamespace(external_id='kb-x')
        stat = SimpleNamespace(is_link=True, owner='张三', document_count=0, path='A/架构.dlink')
        session = SimpleNamespace(execute=AsyncMock(side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: src),
            SimpleNamespace(scalar_one_or_none=lambda: stat),
        ]))
        with self.assertRaises(HTTPException) as ctx:
            await gaps.notify_dingtalk_owner(
                gaps.DingtalkNotifyIn(kb_id='kb-x', node_id='n1'), None, session)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn('快捷方式', ctx.exception.detail)


class DepartmentCoverageTests(unittest.IsolatedAsyncioTestCase):
    """看板占比：1 -（无内容目录数 - dlink 数）÷（文件夹总数 - dlink 数）。

    dlink 行不占应上传文件夹数；但 dlink 算「已有内容」——目录下有文件、
    子文件夹或 dlink 任一存在即为已有内容，放 dlink 的上级目录不算缺失。
    """

    @staticmethod
    def _row(path, document_count=0, folder_count=0, is_link=False):
        return dict(directory_id=path or 'root', kb_id='kb1', kb_name='部门A',
                    directory_path=path or '（根目录）', path=path, owner='',
                    document_count=document_count, is_link=is_link,
                    folder_count=folder_count, source='dingtalk')

    async def test_dlink_child_dirs_count_as_covered(self):
        from app.routes import operate
        rows = [
            self._row('', document_count=1, folder_count=2),  # 根：有文档 → 有内容
            self._row('A', folder_count=1),                   # A 下只有一个 dlink → dlink 算内容
            self._row('A/公共库.dlink', is_link=True),        # dlink 行：不占应上传数
            self._row('B', document_count=2),                # 有文档 → 有内容
            self._row('C'),                                  # 空目录 → 未上传
            self._row('D', folder_count=1),                   # D 下有真实子文件夹 → 有内容
            self._row('D/子目录', document_count=3),          # 有文档 → 有内容
        ]
        session = SimpleNamespace(scalar=AsyncMock(return_value=None))
        with patch('app.routes.knowledge_gaps.all_dingtalk_folder_rows',
                   AsyncMock(return_value=rows)), \
             patch('kb_common.database.SessionLocal', _fake_session_factory(session)):
            result = await operate.knowledge_gap_departments(None)
        item = result['items'][0]
        # 应上传数不含 dlink 行（6 = 7 行 - 1 个 dlink）；只有空目录 C 未上传
        self.assertEqual(item['expected_folder_count'], 6)
        self.assertEqual(item['covered_folder_count'], 5)
        self.assertEqual(item['missing_folder_count'], 1)
        self.assertEqual(item['uploaded_file_count'], 6)
        self.assertEqual(item['coverage_percent'], round(5 * 100 / 6, 2))
        self.assertEqual(result['total']['covered_folder_count'], 5)
