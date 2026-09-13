"""目录采集原文档、目标库分流、递归与失败重试回归。"""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.services.sync import engine
from app.services.sync.dify_sync_client import DifyClient, DifyError
from app.services.sync.dingtalk_sync_client import DingTalkClient, DingTalkError
from app.services.sync.source_files import online_type
from kb_common.models import SyncDocumentMapping, SyncSource
import test_sync as fixtures
from test_sync import make_fake_settings


@pytest.fixture
def setup_engine():
    fixture = fixtures.EngineTests()
    fixture.setUp()
    try:
        with patch.object(engine, "resolve_pipeline_inputs", side_effect=lambda dataset_id, node_id, inputs: inputs):
            yield fixture
    finally:
        fixture.doCleanups()


@pytest.fixture
def client():
    client = DifyClient('http://dify/v1', 'test')
    yield client
    client.close()


def test_directory_pipeline_upload_preserves_pptx_and_parameters(setup_engine):
    f = setup_engine
    original = b'PK\x03\x04original-presentation-with-images'
    path = Path(f.tmp.name) / '原始课件.pptx'
    path.write_bytes(original)
    calls = []

    def handle(request):
        url = request.url.path
        calls.append(url)
        if url == '/v1/datasets':
            return httpx.Response(200, json={'data': [{'id': 'dataset', 'name': 'target'}]})
        if url == '/v1/datasets/dataset':
            # 列表没有模式字段，详情用 pipeline_id 也能识别流水线。
            return httpx.Response(200, json={'id': 'dataset', 'name': 'target', 'pipeline_id': 'p'})
        if url.endswith('/datasource-plugins'):
            return httpx.Response(200, json={'data': [{'node_id': 'node', 'datasource_type': 'local_file'}]})
        if url.endswith('/file-upload'):
            assert original in request.content
            assert 'filename="原始课件.pptx"'.encode() in request.content
            return httpx.Response(201, json={'id': 'upload'})
        if url.endswith('/pipeline/run'):
            data = json.loads(request.content)
            assert data['inputs'] == {'parent_mode': 'full_doc', 'child_length': 300}
            assert data['datasource_info_list'] == [{'reference': 'upload', 'name': path.name}]
            return httpx.Response(200, json={'documents': [{'id': 'new'}], 'batch': 'b'})
        if url.endswith('/indexing-status'):
            return httpx.Response(200, json={'data': [{'indexing_status': 'completed'}]})
        pytest.fail(f'Unexpected request: {request.method} {url}')

    client = DifyClient('http://dify/v1', 'test')
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handle))
    f.dt.walk_tree.return_value = [{'nodeId': 'n', 'name': path.name, 'category': 'DOCUMENT'}]
    with f.sessions() as db:
        source = db.get(SyncSource, f.source.id)
        source.pipeline_inputs = json.dumps({'parent_mode': 'full_doc', 'child_length': 300})
        db.commit()
    with patch.object(engine, 'make_backend', return_value=client), \
         patch.object(engine.SyncEngine, '_fetch', return_value=(path, 'hash')), \
         patch.object(engine, 'get_settings', return_value=make_fake_settings(dify_etl_type='dify', sync_dify_wait_indexing=True)):
        result = engine.SyncEngine(f.source).run()
    assert result['status'] == 'success'
    assert result['created'] == 1
    assert not any('create-by-' in url for url in calls)


def test_one_failure_does_not_stop_remaining_documents(setup_engine):
    f = setup_engine
    f.dt.walk_tree.return_value = [{'nodeId': 'bad', 'name': '失败.pdf'}, {'nodeId': 'ok', 'name': '正常.pdf'}]
    f.dify.upload_file.side_effect = [DifyError('原文档解析失败'), {'document': {'id': 'ok'}, 'batch': 'b'}]
    result = engine.SyncEngine(f.source).run()
    assert result['status'] == 'partial'
    assert (result['created'], result['failed']) == (1, 1)


def test_failed_pipeline_replacement_preserves_old_document(client):
    with patch.object(client, 'upload_file_via_pipeline', return_value={'document': {'id': 'new'}, 'batch': 'b'}), \
         patch.object(client, 'wait_indexing', side_effect=DifyError('解析失败')), \
         patch.object(client, 'delete_document') as delete:
        with pytest.raises(DifyError, match='解析失败'):
            client.update_file_via_pipeline('dataset', 'old', Path('source.docx'))
    delete.assert_called_once_with('dataset', 'new')


def test_pipeline_replacement_deletes_old_only_after_indexing(client):
    order = []
    with patch.object(client, 'upload_file_via_pipeline', return_value={'document': {'id': 'new'}, 'batch': 'b'}), \
         patch.object(client, 'wait_indexing', side_effect=lambda *a, **kw: order.append('indexed')), \
         patch.object(client, 'delete_document', side_effect=lambda *a: order.append(a[-1])):
        client.update_file_via_pipeline('dataset', 'old', Path('source.docx'))
    assert order == ['indexed', 'old']


def test_general_failed_document_can_be_replaced(client, tmp_path):
    calls = []
    def handle(r):
        calls.append((r.method, r.url.path))
        if r.url.path.endswith('/update-by-file'):
            return httpx.Response(400, json={'message': 'Document is not available'})
        if r.url.path.endswith('/documents/old') and r.method == 'GET':
            return httpx.Response(200, json={'indexing_status': 'error'})
        if r.url.path.endswith('/create-by-file'):
            return httpx.Response(200, json={'document': {'id': 'new'}, 'batch': 'batch'})
        if r.url.path.endswith('/indexing-status'):
            return httpx.Response(200, json={'data': [{'indexing_status': 'completed'}]})
        return httpx.Response(200, json={'id': 'dataset', 'document_count': 1})
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handle))
    path = tmp_path / '原文件.pdf'
    path.write_bytes(b'%PDF-1.4 original')
    result = client.update_file('dataset', 'old', path)
    assert result['document']['id'] == 'new'
    assert calls[-1] == ('DELETE', '/v1/datasets/dataset/documents/old')


def test_id_wins_over_renamed_or_duplicate_name(client):
    with patch.object(client, 'get_dataset', return_value={'id': 'chosen', 'name': '新名称'}), \
         patch.object(client, 'find_dataset_by_name') as find:
        assert client.resolve_dataset('chosen', '旧名称')['name'] == '新名称'
    find.assert_not_called()


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
            assert {n['nodeId'] for n in client.walk_tree('root')} == {'pdf', 'doc', 'child', 'sheet'}
        with patch.object(client, 'list_nodes', return_value=[{'nodeId': 'folder', 'type': 'FOLDER'}]):
            with pytest.raises(DingTalkError, match='最大遍历深度'):
                client.walk_tree('root', max_depth=0)
    finally:
        client.close()


def test_source_metadata_preserves_original_format():
    assert online_type({'category': 'ALIDOC', 'name': '原文.pdf'}) == ''
    assert online_type({'category': 'ALIDOC', 'name': '在线表格', 'extension': '.AXLS'}) == 'axls'


def test_pipeline_defaults_exclude_other_datasource_required_fields():
    from unittest.mock import MagicMock
    from app.services.sync import dify_pipeline_vars as variables
    schema = {
        'url': {'belong_to_node_id': 'web-node', 'required': True},
        'length': {'belong_to_node_id': 'shared', 'type': 'number', 'default_value': 256, 'required': True},
        'clean': {'belong_to_node_id': 'file-node', 'type': 'checkbox', 'default_value': True, 'required': True},
    }
    db_engine = MagicMock()
    db_engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = json.dumps(schema)
    with patch.object(variables, '_engine', return_value=db_engine):
        result = variables.resolve_pipeline_inputs('dataset', 'file-node', {'clean': False})
    assert result == {'length': 256, 'clean': False}


def test_changing_target_clears_old_ids_but_keeps_document_switches(setup_engine):
    from app.routes import sync_route
    from app.schemas import SyncSourceUpdate
    f = setup_engine
    with f.sessions() as db:
        source = db.get(SyncSource, f.source.id)
        source.dify_dataset_id = 'old-dataset'
        db.add(SyncDocumentMapping(source_id=source.id, node_id='n', name='原文.pdf', category='DOCUMENT',
                                   dify_document_id='old-document', enabled=False, status='synced'))
        db.commit()
        f.dify.resolve_dataset.return_value = {'id': 'new-dataset', 'name': '新目标'}
        with patch.object(sync_route, 'make_backend', return_value=f.dify), \
             patch.object(sync_route, 'reload_sync_jobs'):
            sync_route.update_source(source.id, SyncSourceUpdate(dify_dataset_id='new-dataset', dify_dataset_name='新目标'), db)
        mapping = db.query(SyncDocumentMapping).one()
        assert mapping.dify_document_id is None
        assert mapping.enabled is False
        assert mapping.status == 'pending'
        f.dify.delete_document.assert_not_called()


def test_preview_and_execution_agree_on_pipeline_pptx(setup_engine):
    from app.routes import sync_route
    f = setup_engine
    f.dify.resolve_dataset.return_value = {'id': 'dataset', 'name': 'target', 'runtime_mode': 'rag_pipeline'}
    f.dt.walk_tree.return_value = [{'nodeId': 'ppt', 'name': '原始课件.pptx', 'category': 'DOCUMENT'}]
    with f.sessions() as db, \
         patch.object(sync_route, 'make_backend', return_value=f.dify), \
         patch.object(sync_route, 'make_dingtalk_client', return_value=f.dt):
        preview = sync_route.preview_source(f.source.id, db)
    assert preview[0]['action'] == '新增'
    assert preview[0]['node_id'] == 'ppt'
