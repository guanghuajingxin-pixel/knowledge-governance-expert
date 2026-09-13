"""原文件下载完整性校验；不解码或改写文档内容。"""
import base64
import hashlib
from email.message import Message
from urllib.parse import unquote, urlparse

import httpx


def downloaded_file(response: httpx.Response, url: str) -> tuple[bytes, str]:
    response.raise_for_status()
    content = response.content
    if not content:
        raise ValueError("原文件下载为空")
    length = response.headers.get("content-length")
    if length and not response.headers.get("content-encoding") and int(length) != len(content):
        raise ValueError("原文件下载不完整：返回长度与 Content-Length 不符")
    expected = response.headers.get("content-md5")
    if expected and base64.b64encode(hashlib.md5(content).digest()).decode() != expected:
        raise ValueError("原文件下载校验失败：Content-MD5 不一致")
    # ETag 是不透明标识（加密或多分片对象不一定是 MD5），不能据此拒收原文件。
    message = Message()
    message["content-disposition"] = response.headers.get("content-disposition", "")
    filename = message.get_filename() or unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return content, filename
