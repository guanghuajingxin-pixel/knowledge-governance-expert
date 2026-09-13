import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

from kb_common.clients import dify_client
from kb_common.clients.document_upload import MAX_UPLOAD_BYTES, prepare_document


@pytest.mark.parametrize('name', ['报告.PDF', '报告.docx', '报告.pptx', '数据.xlsx', '数据.xls', '数据.csv', '说明.txt', '说明.md', '页面.html', '旧版.doc', '旧版.ppt'])
def test_passthrough(name):
    assert prepare_document(name, b'content') == (name, b'content')


@pytest.mark.parametrize('name,content', [('a.zip', b'zip'), ('a.pdf', b''), ('a.txt', b'x' * (MAX_UPLOAD_BYTES + 1)), ('a.pptx', b'')])
def test_invalid_upload(name, content):
    with pytest.raises(ValueError):
        prepare_document(name, content)


@pytest.mark.parametrize('form,indexing,count', [('hierarchical_model', 'high_quality', 2), ('text_model', 'economy', 1), ('text_model', None, 0)])
def test_upload_inherits_dataset_and_multipart(form, indexing, count):
    from email import policy
    from email.parser import BytesParser
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, json={'doc_form': form, 'indexing_technique': indexing, 'document_count': count})
        message = BytesParser(policy=policy.default).parsebytes(
            f'Content-Type: {request.headers["content-type"]}\r\n\r\n'.encode() + request.content
        )
        parts = {part.get_param('name', header='content-disposition'): part for part in message.iter_parts()}
        assert parts['file'].get_payload(decode=True) == b'hello'
        assert parts['data'].get_filename() is None
        payload = json.loads(parts['data'].get_payload(decode=True))
        assert payload['doc_form'] == form
        assert payload['indexing_technique'] == (indexing or 'high_quality')
        assert ('process_rule' in payload) == (count == 0)
        return httpx.Response(200, json={'document': {'id': 'new-document'}, 'batch': 'batch'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        result = asyncio.run(dify_client.upload_document('dataset', 'test.txt', b'hello'))
    assert result['document']['id'] == 'new-document'


def test_keeps_parameter_error_detail():
    def handle(request):
        return httpx.Response(400, json={'code': 'invalid_param', 'message': 'doc_form is different from the dataset doc_form.'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        with pytest.raises(RuntimeError, match='doc_form is different'):
            asyncio.run(dify_client.upload_document('dataset', 'test.txt', b'hello'))


def test_pipeline_dataset_uses_three_step_flow():
    """流水线数据集必须走 datasource-plugins → file-upload → pipeline/run 三步接口。"""
    dify_client._PIPELINE_NODE_CACHE.clear()
    calls: list[str] = []

    def handle(request):
        path = request.url.path
        calls.append(f"{request.method} {path}")
        if path == '/v1/datasets/pipeline-ds':
            return httpx.Response(200, json={'runtime_mode': 'rag_pipeline', 'id': 'pipeline-ds'})
        if path == '/v1/datasets/pipeline-ds/pipeline/datasource-plugins':
            return httpx.Response(200, json=[
                {'datasource_type': 'online_doc', 'node_id': 'skip-me'},
                {'datasource_type': 'local_file', 'node_id': 'node-abc'},
            ])
        if path == '/v1/datasets/pipeline/file-upload':
            # Dify 官方文档：file-upload 返回 HTTP 201
            return httpx.Response(201, json={
                'id': 'ref-xyz', 'name': 'test.txt', 'size': 5,
                'extension': 'txt', 'mime_type': 'text/plain',
            })
        if path == '/v1/datasets/pipeline-ds/pipeline/run':
            payload = json.loads(request.content)
            assert payload['start_node_id'] == 'node-abc'
            assert payload['datasource_type'] == 'local_file'
            assert payload['datasource_info_list'] == [{'reference': 'ref-xyz', 'name': 'test.txt'}]
            assert payload['response_mode'] == 'blocking'
            assert payload['is_published'] is True
            # 未填写参数时使用目标流水线默认值，不再注入某个模板的分段长度
            assert payload['inputs'] == {}
            # 真实响应结构（Dify 1.16.1 实测）：{batch, dataset, documents[]} 顶层
            return httpx.Response(200, json={
                'batch': '20260911155940940899',
                'dataset': {
                    'id': 'pipeline-ds', 'name': 'test-ds',
                    'chunk_structure': 'text_model',
                },
                'documents': [{
                    'id': 'doc-1',
                    'name': 'test.txt',
                    'indexing_status': 'waiting',
                    'data_source_type': 'local_file',
                    'position': 1,
                    'error': None,
                    'enabled': True,
                }],
            })
        return httpx.Response(404, json={'message': f'unhandled {path}'})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), \
         patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        result = asyncio.run(dify_client.upload_document('pipeline-ds', 'test.txt', b'hello'))

    # 归一化后的返回结构必须与 create-by-file 对齐
    assert result['document']['id'] == 'doc-1'
    assert result['document']['name'] == 'test.txt'
    assert result['document']['indexing_status'] == 'waiting'
    assert result['document']['data_source_type'] == 'local_file'
    assert result['batch'] == '20260911155940940899'
    assert result['runtime_mode'] == 'rag_pipeline'
    # 三步接口全部命中，且未调用 create-by-file
    assert 'GET /v1/datasets/pipeline-ds' in calls
    assert 'GET /v1/datasets/pipeline-ds/pipeline/datasource-plugins' in calls
    assert 'POST /v1/datasets/pipeline/file-upload' in calls
    assert 'POST /v1/datasets/pipeline-ds/pipeline/run' in calls
    assert not any('create-by-file' in c for c in calls)


def test_pipeline_node_id_cached_within_ttl():
    """同一 dataset 5 分钟内多次上传，datasource-plugins 只查询一次。"""
    dify_client._PIPELINE_NODE_CACHE.clear()
    datasource_hits = {'count': 0}

    def handle(request):
        path = request.url.path
        if path == '/v1/datasets/pipeline-ds':
            return httpx.Response(200, json={'runtime_mode': 'rag_pipeline'})
        if path == '/v1/datasets/pipeline-ds/pipeline/datasource-plugins':
            datasource_hits['count'] += 1
            return httpx.Response(200, json=[{'datasource_type': 'local_file', 'node_id': 'node-cached'}])
        if path == '/v1/datasets/pipeline/file-upload':
            return httpx.Response(201, json={'id': 'ref-1'})
        if path == '/v1/datasets/pipeline-ds/pipeline/run':
            return httpx.Response(200, json={
                'batch': 'b',
                'dataset': {'id': 'pipeline-ds'},
                'documents': [{'id': 'd', 'name': 'x.txt', 'indexing_status': 'waiting'}],
            })
        return httpx.Response(404)

    original_async_client = httpx.AsyncClient  # 在 patch 之前捕获原类，避免 lambda 递归调用被 patch 的自身

    def client_factory(**kw):
        return original_async_client(transport=httpx.MockTransport(handle))

    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), \
         patch.object(dify_client.httpx, 'AsyncClient', client_factory):
        asyncio.run(dify_client.upload_document('pipeline-ds', 'a.txt', b'1'))
        asyncio.run(dify_client.upload_document('pipeline-ds', 'b.txt', b'2'))
        asyncio.run(dify_client.upload_document('pipeline-ds', 'c.txt', b'3'))

    assert datasource_hits['count'] == 1, '5 分钟缓存内 datasource-plugins 应只查询 1 次'


def test_pipeline_missing_local_file_node_raises():
    """流水线未配置本地文件数据源节点时，必须报明确的中文错误。"""
    dify_client._PIPELINE_NODE_CACHE.clear()

    def handle(request):
        path = request.url.path
        if path == '/v1/datasets/no-file-node':
            return httpx.Response(200, json={'runtime_mode': 'rag_pipeline'})
        if path == '/v1/datasets/no-file-node/pipeline/datasource-plugins':
            return httpx.Response(200, json=[{'datasource_type': 'online_doc', 'node_id': 'x'}])
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), \
         patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        with pytest.raises(RuntimeError, match='未配置本地文件数据源节点'):
            asyncio.run(dify_client.upload_document('no-file-node', 'a.txt', b'x'))


def test_pipeline_run_status_failed_raises():
    """pipeline/run 返回 HTTP 500 + pipeline_run_error 时，必须带上 Dify 错误信息抛出。

    真实场景：流水线定义了 max_chunk_length 输入变量但 inputs 没传，
    Dify 报 500 {"code":"pipeline_run_error","message":"max_chunk_length is required in input form"}。
    """
    dify_client._PIPELINE_NODE_CACHE.clear()

    def handle(request):
        path = request.url.path
        if path == '/v1/datasets/pipeline-ds':
            return httpx.Response(200, json={'runtime_mode': 'rag_pipeline'})
        if path == '/v1/datasets/pipeline-ds/pipeline/datasource-plugins':
            return httpx.Response(200, json=[{'datasource_type': 'local_file', 'node_id': 'n'}])
        if path == '/v1/datasets/pipeline/file-upload':
            return httpx.Response(201, json={'id': 'r'})
        if path == '/v1/datasets/pipeline-ds/pipeline/run':
            return httpx.Response(500, json={
                'code': 'pipeline_run_error',
                'message': 'max_chunk_length is required in input form',
                'status': 500,
            })
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), \
         patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(dify_client.upload_document('pipeline-ds', 'a.txt', b'x'))
    msg = str(exc.value)
    assert 'max_chunk_length is required in input form' in msg
    assert '500' in msg


def test_pipeline_outputs_missing_document_id_raises():
    """HTTP 200 但 documents 为空数组、兜底 data.outputs 也缺 document_id 时，必须提示检查『知识索引』节点。"""
    dify_client._PIPELINE_NODE_CACHE.clear()

    def handle(request):
        path = request.url.path
        if path == '/v1/datasets/pipeline-ds':
            return httpx.Response(200, json={'runtime_mode': 'rag_pipeline'})
        if path == '/v1/datasets/pipeline-ds/pipeline/datasource-plugins':
            return httpx.Response(200, json=[{'datasource_type': 'local_file', 'node_id': 'n'}])
        if path == '/v1/datasets/pipeline/file-upload':
            return httpx.Response(201, json={'id': 'r'})
        if path == '/v1/datasets/pipeline-ds/pipeline/run':
            # 极端场景：流水线跑完但没创建文档（末尾缺知识索引节点）
            return httpx.Response(200, json={
                'batch': '',
                'dataset': {'id': 'pipeline-ds'},
                'documents': [],
            })
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch.object(dify_client, '_base_url', return_value='http://dify.test/v1'), \
         patch.object(dify_client.httpx, 'AsyncClient', return_value=client):
        with pytest.raises(RuntimeError, match='知识索引'):
            asyncio.run(dify_client.upload_document('pipeline-ds', 'a.txt', b'x'))
