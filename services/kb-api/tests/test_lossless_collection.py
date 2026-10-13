"""原文件传输与官方导出契约回归。"""
import base64
import hashlib
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from app.services.sync import export_service, source_files
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
