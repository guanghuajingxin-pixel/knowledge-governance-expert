import asyncio
import io
import json
import zipfile
from unittest.mock import patch

import httpx
import pytest

from kb_common.clients import dify_client
from kb_common.clients.document_upload import MAX_UPLOAD_BYTES, prepare_document


@pytest.mark.parametrize('name', ['报告.PDF', '报告.docx', '数据.xlsx', '数据.xls', '数据.csv', '说明.txt', '说明.md', '页面.html', '旧版.doc', '旧版.ppt'])
def test_passthrough(name):
    assert prepare_document(name, b'content') == (name, b'content')


@pytest.mark.parametrize('name,content', [('a.zip', b'zip'), ('a.pdf', b''), ('a.txt', b'x' * (MAX_UPLOAD_BYTES + 1)), ('a.pptx', b'invalid')])
def test_invalid_upload(name, content):
    with pytest.raises(ValueError):
        prepare_document(name, content)


def test_pptx_text_in_slide_order():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for number in [10, 2, 1]:
            archive.writestr(f'ppt/slides/slide{number}.xml', f'<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>内容{number}</a:t></a:p>')
    name, content = prepare_document('报告.pptx', stream.getvalue())
    assert name == '报告.md'
    assert content.decode().index('内容1') < content.decode().index('内容2') < content.decode().index('内容10')


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
