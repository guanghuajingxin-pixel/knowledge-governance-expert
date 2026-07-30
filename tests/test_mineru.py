"""MinerU 客户端单测。

环境无真实 MINERU_API_KEY，故云路径用 mock 的 AsyncClient 端到端验证
「申请上传 -> PUT 原文件 -> 轮询 -> 下载 zip -> 取 full.md」逻辑闭环；
另覆盖 txt 本地兜底与二进制无 key 报错。
"""
import asyncio
import io
import zipfile

import pytest

from kb_common.clients import mineru_client


class _FakeResp:
    """httpx.Response 的最小替身。"""

    def __init__(self, payload=None, content=None):
        self._payload = payload
        self.content = content
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _make_result_zip(md_text: str = "Hello parsed") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("full.md", md_text)
    return buf.getvalue()


class _FakeClient:
    """替换 httpx.AsyncClient：按 URL 路由返回预设响应，不做任何网络 IO。

    - POST file-urls/batch -> 返回固定 batch_id + put_url
    - PUT put_url -> 记录收到的字节（断言为裸文件而非 zip）
    - GET extract-results/batch/{id} -> 第 1 次 running，第 2 次 done
    - GET full_zip_url -> 返回含 full.md 的 zip
    """

    PUT_URL = "https://put.example.com/upload"
    ZIP_URL = "https://zip.example.com/r.zip"
    BATCH_ID = "batch-id-xyz"

    def __init__(self, *args, **kwargs):
        self.poll_count = 0
        self.put_content = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.last_post_body = json
        return _FakeResp(payload={
            "code": 0,
            "data": {"batch_id": self.BATCH_ID, "file_urls": [self.PUT_URL]},
        })

    async def put(self, url, content=None, headers=None):
        assert url == self.PUT_URL
        self.put_content = content
        return _FakeResp(payload={"code": 0})

    async def get(self, url, headers=None):
        if "extract-results/batch" in url:
            self.poll_count += 1
            if self.poll_count == 1:
                return _FakeResp(payload={
                    "code": 0,
                    "data": {"extract_result": [{"state": "running"}]},
                })
            return _FakeResp(payload={
                "code": 0,
                "data": {"extract_result": [
                    {"state": "done", "full_zip_url": self.ZIP_URL},
                ]},
            })
        # 结果 zip 下载
        assert url == self.ZIP_URL
        return _FakeResp(content=_make_result_zip("Hello parsed"))


async def _no_sleep(*_a, **_k):
    """轮询间隔的 no-op 替身，避免单测里真实 sleep 5s。"""
    return None


def test_cloud_parse_mocked_end_to_end(monkeypatch):
    """云路径逻辑闭环：submit -> poll(running->done) -> zip -> full.md。"""
    monkeypatch.setattr(mineru_client.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(mineru_client.asyncio, "sleep", _no_sleep)

    pdf_bytes = b"%PDF-1.4 fake pdf body"
    result = asyncio.run(
        mineru_client.parse(pdf_bytes, "doc.pdf", api_key="fake")
    )

    assert result == {"markdown": "Hello parsed", "pages": 1}


def test_cloud_parse_uploads_raw_bytes_not_zip(monkeypatch):
    """官方文档复核结论：PUT 上传裸文件字节，不打包 zip，无 Content-Type。"""
    fake = _FakeClient()
    monkeypatch.setattr(mineru_client.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(mineru_client.asyncio, "sleep", _no_sleep)

    pdf_bytes = b"%PDF-1.4 raw bytes here"
    asyncio.run(mineru_client.parse(pdf_bytes, "doc.pdf", api_key="fake"))

    # PUT 收到的应是原始 PDF 字节，而非 zip（zip 魔数是 PK\x03\x04）
    assert fake.put_content == pdf_bytes
    assert not fake.put_content.startswith(b"PK")


def test_cloud_parse_submits_files_as_name_dicts(monkeypatch):
    """复核结论：file-urls/batch 的 files 为 [{name: filename}] 字典列表。"""
    fake = _FakeClient()
    monkeypatch.setattr(mineru_client.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(mineru_client.asyncio, "sleep", _no_sleep)

    asyncio.run(mineru_client.parse(b"%PDF", "report.pdf", api_key="fake"))

    body = fake.last_post_body
    assert body["files"] == [{"name": "report.pdf"}]


def test_txt_local_fallback_no_key():
    """txt 走本地直读，无需 key。"""
    r = asyncio.run(mineru_client.parse(b"hello world", "a.txt"))
    assert r == {"markdown": "hello world", "pages": 1}


def test_md_local_fallback_no_key():
    r = asyncio.run(mineru_client.parse("# 标题\n正文".encode(), "a.md"))
    assert r["markdown"] == "# 标题\n正文" and r["pages"] == 1


def test_binary_without_key_raises():
    """二进制格式未配置 key 时抛 RuntimeError，消息含「需配置」。"""
    with pytest.raises(RuntimeError, match="需配置"):
        asyncio.run(mineru_client.parse(b"%PDF", "a.pdf"))


def test_binary_without_key_raises_for_docx():
    with pytest.raises(RuntimeError, match="需配置"):
        asyncio.run(mineru_client.parse(b"PK", "a.docx"))


def test_unsupported_format_raises():
    """不在白名单的扩展名抛 RuntimeError，消息含「不支持」。"""
    with pytest.raises(RuntimeError, match="不支持"):
        asyncio.run(mineru_client.parse(b"???", "a.weird"))
