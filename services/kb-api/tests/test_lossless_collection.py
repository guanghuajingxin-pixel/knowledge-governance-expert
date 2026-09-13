"""原文件传输、官方导出与流水线输入契约回归。"""
import base64
import hashlib
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import yaml
from fastapi import HTTPException
from app.services.sync import export_service, pipeline_schema, source_files
from kb_common.clients.source_integrity import downloaded_file


def response(content=b'original\x00\xff', **headers):
    return httpx.Response(200, content=content, headers=headers, request=httpx.Request('GET', 'https://oss/source'))


def test_download_preserves_bytes_and_unicode_filename():
    original = b'original\x00\xff'
    digest = base64.b64encode(hashlib.md5(original).digest()).decode()
    actual, name = downloaded_file(response(original, **{'Content-MD5': digest,
        'Content-Disposition': "attachment; filename*=UTF-8''%E5%8E%9F%E6%96%87.docx"}), 'https://oss/random')
    assert actual == original
    assert name == '原文.docx'


@pytest.mark.parametrize('headers,message', [({'Content-Length': '999'}, '不完整'), ({'Content-MD5': 'invalid'}, '校验失败')])
def test_incomplete_download_fails(headers, message):
    with pytest.raises(ValueError, match=message):
        downloaded_file(response(**headers), 'https://oss/source')


def test_etag_is_opaque_and_compressed_length_is_not_decoded_size():
    res = response(**{'ETag': '"00000000000000000000000000000000"'})
    res.headers['Content-Encoding'] = 'gzip'
    res.headers['Content-Length'] = '999'
    assert downloaded_file(res, 'https://oss/source')[0] == res.content


@pytest.mark.parametrize('ext,exporter,command', [('adoc', export_service.export_alidoc, ['doc', '+export']), ('axls', export_service.export_axls, ['sheet', 'export'])])
def test_official_export_uses_fresh_relative_output(tmp_path, ext, exporter, command):
    suffix = 'docx' if ext == 'adoc' else 'xlsx'
    target = tmp_path / f'原文.{suffix}'
    target.write_bytes(b'previous-version')
    def run(args, timeout, cwd=None):
        assert args[:2] == command
        name = args[args.index('--output') + 1]
        assert not Path(name).is_absolute()
        assert cwd != tmp_path
        assert not (cwd / name).exists()
        (cwd / name).write_bytes(b'new-export')
        return subprocess.CompletedProcess(args, 0, '', '')
    with patch.object(export_service, '_run_dws', side_effect=run):
        assert exporter('node', f'原文.{ext}', tmp_path).read_bytes() == b'new-export'
    with patch.object(export_service, '_run_dws', return_value=subprocess.CompletedProcess([], 0, '', '')):
        with pytest.raises(export_service.ExportError):
            exporter('node', f'原文.{ext}', tmp_path)
    assert target.read_bytes() == b'new-export'


def test_binary_source_never_uses_online_export(tmp_path):
    dt = Mock()
    dt.download_document.return_value = (b'\x00\xfforiginal', 'random')
    node = {'nodeId': 'wiki', 'name': '年度规划V1.0', 'extension': 'pptx', 'category': 'ALIDOC', 'size': 10}
    with patch.object(export_service, 'export_online_doc') as export:
        path = source_files.fetch_source_file(dt, node, tmp_path)
    assert path.name == '年度规划V1.0.pptx'
    assert path.read_bytes() == b'\x00\xfforiginal'
    export.assert_not_called()
    with pytest.raises(ValueError, match='大小'):
        source_files.fetch_source_file(dt, {**node, 'size': 11}, tmp_path)


def pipeline_bytes():
    return yaml.safe_dump({'kind': 'rag_pipeline', 'rag_pipeline': {'name': '测试'}, 'workflow': {
        'graph': {'nodes': [{'id': 'file', 'data': {'provider_type': 'local_file'}}]},
        'rag_pipeline_variables': [
            {'variable': 'parent_mode', 'label': '模式', 'type': 'select', 'options': ['paragraph', 'full_doc'], 'required': True, 'default_value': 'paragraph', 'belong_to_node_id': 'shared'},
            {'variable': 'clean_1', 'type': 'checkbox', 'required': True, 'default_value': True, 'belong_to_node_id': 'shared'},
            {'variable': 'limit', 'type': 'number', 'required': True, 'default_value': 1024, 'belong_to_node_id': 'file'},
            {'variable': 'jina_reader_url', 'required': True, 'belong_to_node_id': 'webpage'},
        ]}}).encode()


def test_import_filters_other_branches_and_preserves_false_zero():
    schema = pipeline_schema.parse_pipeline(pipeline_bytes(), 'file')
    result = pipeline_schema.apply_inputs(schema['variables'], {'clean_1': False, 'limit': 0, 'jina_reader_url': 'ignored'})
    assert result == {'parent_mode': 'paragraph', 'clean_1': False, 'limit': 0}
    assert len(pipeline_schema.schema_key('https://dify/v1', 'uuid')) <= 64


@pytest.mark.parametrize('inputs', [{'parent_mode': 'invalid'}, {'limit': True}, {'clean_1': 'false'}, {'parent_mode': '   '}, {'limit': float('nan')}])
def test_invalid_inputs_rejected_before_push(inputs):
    with pytest.raises(ValueError):
        pipeline_schema.apply_inputs(pipeline_schema.parse_pipeline(pipeline_bytes(), 'file')['variables'], inputs)


@pytest.mark.parametrize('content,node', [(b'!!python/object:evil {}', 'file'), (b'x' * (1024*1024+1), 'file'), (pipeline_bytes(), 'other')])
def test_import_rejects_unsafe_or_wrong_pipeline(content, node):
    with pytest.raises(ValueError):
        pipeline_schema.parse_pipeline(content, node)


def test_single_sync_validates_before_download_and_preserves_bytes():
    import asyncio
    from app.routes import dify_route as route
    original = b'\x00\xfforiginal-office-file'
    async def run():
        with patch.object(route, '_runtime_config', AsyncMock(return_value=('http://dify/v1', 'test'))), \
             patch('app.services.sync.dify_pipeline_vars.prepare_inputs_for_dataset', side_effect=ValueError('缺少参数')) as prepare, \
             patch.object(source_files, 'download_single_source', return_value=('原文.pptx', original, 'file')) as download, \
             patch.object(route.minio_client, 'upload_bytes'), \
             patch.object(route.dify_client, 'upload_document', AsyncMock(return_value={'document': {'id': 'doc'}})) as upload, \
             patch.object(route, '_save_dingtalk_mapping', AsyncMock()):
            body = route.SyncDingTalkIn(node_id='node', name='界面旧名字.pdf', pipeline_inputs={'child_length': 300})
            sync = route.sync_dingtalk_file.__wrapped__
            with pytest.raises(HTTPException) as error:
                await sync('dataset', body, s=Mock())
            assert error.value.status_code == 422
            download.assert_not_called()
            prepare.side_effect = None
            prepare.return_value = {'child_length': 300, 'parent_mode': 'paragraph'}
            result = await sync('dataset', body, s=Mock())
            upload.assert_awaited_once_with('dataset', '原文.pptx', original, inputs=prepare.return_value)
            assert result['source_sha256'] == hashlib.sha256(original).hexdigest()
            assert result['source_size'] == len(original)
    asyncio.run(run())
