"""目录采集原文档、本地文档库目标、递归与失败重试回归。"""
from unittest.mock import patch

import pytest

from app.services.sync import engine
from app.services.sync.dingtalk_sync_client import DingTalkClient, DingTalkError
from app.services.sync.source_files import online_type
from kb_common.models import SyncDocumentMapping, SyncSource
import test_sync as fixtures


@pytest.fixture
def setup_engine():
    fixture = fixtures.EngineTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def test_one_failure_does_not_stop_remaining_documents(setup_engine):
    f = setup_engine
    f.dt.walk_tree.return_value = [{'nodeId': 'bad', 'name': '失败.pdf'}, {'nodeId': 'ok', 'name': '正常.pdf'}]
    f.backend.upload_file.side_effect = [RuntimeError('原文档解析失败'), {'document': {'id': 'ok'}, 'batch': ''}]
    result = engine.SyncEngine(f.source).run()
    assert result['status'] == 'partial'
    assert (result['created'], result['failed']) == (1, 1)


def test_walk_collects_folders_and_document_children():
    client = DingTalkClient('key', 'secret', 'operator')
    tree = {
        'root': [{'nodeId': 'folder', 'name': '目录', 'type': 'FOLDER'},
                 {'nodeId': 'doc', 'name': '正文.adoc', 'category': 'ALIDOC', 'hasChildren': True},
                 {'nodeId': 'other', 'name': '另一目录', 'category': 'OTHER', 'hasChildren': True}],
        'folder': [{'nodeId': 'pdf', 'name': '文件.pdf', 'category': 'DOCUMENT'}],
        'doc': [{'nodeId': 'child', 'name': '附件.docx', 'category': 'DOCUMENT'}],
        'other': [{'nodeId': 'sheet', 'name': '表格.xlsx', 'category': 'DOCUMENT'}],
    }
    try:
        with patch.object(client, 'list_nodes', side_effect=lambda node_id, **kw: tree[node_id]):
            # use_cache=False：绕过 10 分钟遍历缓存，否则深度校验分支不会真正执行
            assert {n['nodeId'] for n in client.walk_tree('root', use_cache=False)} == {'pdf', 'doc', 'child', 'sheet'}
        with patch.object(client, 'list_nodes', return_value=[{'nodeId': 'folder', 'type': 'FOLDER'}]):
            with pytest.raises(DingTalkError, match='最大遍历深度'):
                client.walk_tree('root', max_depth=0, use_cache=False)
    finally:
        client.close()


def test_source_metadata_preserves_original_format():
    assert online_type({'category': 'ALIDOC', 'name': '原文.pdf'}) == ''
    assert online_type({'category': 'ALIDOC', 'name': '在线表格', 'extension': '.AXLS'}) == 'axls'


def test_changing_target_clears_old_ids_but_keeps_document_switches(setup_engine):
    from app.routes import sync_route
    from app.schemas import SyncSourceUpdate
    f = setup_engine
    with f.sessions() as db:
        source = db.get(SyncSource, f.source.id)
        source.dataset_id = 'old-dataset'
        db.add(SyncDocumentMapping(source_id=source.id, node_id='n', name='原文.pdf', category='DOCUMENT',
                                   document_id='old-document', enabled=False, status='synced'))
        db.commit()
        f.backend.resolve_dataset.return_value = {'id': 'new-dataset', 'name': '新目标'}
        with patch.object(sync_route, 'make_library_backend', return_value=f.backend), \
             patch.object(sync_route, 'reload_sync_jobs'):
            sync_route.update_source(source.id, SyncSourceUpdate(dataset_id='new-dataset', dataset_name='新目标'), db)
        mapping = db.query(SyncDocumentMapping).one()
        assert mapping.document_id is None
        assert mapping.enabled is False
        assert mapping.status == 'pending'
        f.backend.delete_document.assert_not_called()
