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


def test_walk_tree_iter_yields_before_subtree_finishes():
    """流式遍历：首个目录列举完成即产出文件节点，不等子目录遍历结束。

    「添加知识」整库导入首批秒级可见的基础：子目录列举被阻塞时，
    根目录的文件节点已可被消费（编目据此边遍历边落库）。
    """
    import threading

    client = DingTalkClient('key', 'secret', 'operator')
    subtree_gate = threading.Event()
    tree = {
        'root': [{'nodeId': 'doc', 'name': '正文.adoc', 'category': 'ALIDOC'},
                 {'nodeId': 'folder', 'name': '子目录', 'category': 'OTHER', 'hasChildren': True}],
    }

    def list_nodes(node_id, **kw):
        if node_id == 'folder':
            subtree_gate.wait(timeout=5)
            return []
        return tree[node_id]

    try:
        with patch.object(client, 'list_nodes', side_effect=list_nodes):
            gen = client.walk_tree_iter('root')
            assert [n['nodeId'] for n in next(gen)] == ['doc']  # 子目录仍阻塞时已产出
            subtree_gate.set()
            assert list(gen) == []  # 子目录无文件：无更多产出，遍历正常收尾
    finally:
        subtree_gate.set()
        client.close()


def test_source_metadata_preserves_original_format():
    assert online_type({'category': 'ALIDOC', 'name': '原文.pdf'}) == ''
    assert online_type({'category': 'ALIDOC', 'name': '在线表格', 'extension': '.AXLS'}) == 'axls'


def test_edit_quiet_elapsed():
    from datetime import datetime, timedelta, timezone

    def ts(minutes_ago: float) -> int:
        return int((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp() * 1000)

    # 禁用静默期（quiet_minutes<=0）：恒 True（变更即同步）
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': ts(0)}, 0) is True
    # 编辑中（修改时间 5 分钟前 < 10 分钟窗口）→ 不静默
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': ts(5)}, 10) is False
    # 编辑结束（修改时间 15 分钟前 ≥ 10 分钟窗口）→ 静默超时
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': ts(15)}, 10) is True
    # 边界：恰好达到窗口 → True（>= 语义）
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': ts(10.1)}, 10) is True
    # 时间戳缺失 / 非法：恒 True（保持旧行为，批处理 content_hash 兜底）
    assert engine._edit_quiet_elapsed({}, 10) is True
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': 'not-a-number'}, 10) is True
    assert engine._edit_quiet_elapsed({'modifiedTimestamp': 0}, 10) is True


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
        with patch.object(sync_route, 'make_library_backend', return_value=f.backend):
            sync_route.update_source(source.id, SyncSourceUpdate(dataset_id='new-dataset', dataset_name='新目标'), db)
        mapping = db.query(SyncDocumentMapping).one()
        assert mapping.document_id is None
        assert mapping.enabled is False
        assert mapping.status == 'pending'
        f.backend.delete_document.assert_not_called()
