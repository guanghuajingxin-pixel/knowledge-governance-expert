"""文档解析客户端。

- txt/md/csv：本地直读（无需 key），保持不变。
- PDF/DOCX/PPTX/XLSX/HTML 等二进制格式：走 MinerU 云 API 解析，需配置
  ``MINERU_API_KEY``；未配置时抛 ``RuntimeError`` 给出明确提示。

云 API 契约（WebFetch 复核 https://mineru.net/apiManage ，2026-07）：
  1. ``POST {base}/file-urls/batch`` 申请预签名上传 URL，body::
         {"enable_formula": True, "enable_table": True, "language": "ch",
          "files": [{"name": "<filename>"}]}
     带 ``Authorization: Bearer <key>`` -> ``{"code":0,"data":{"batch_id":"...","file_urls":["https://..."]}}``。
  2. ``PUT`` 原始文件字节到 ``file_urls[0]``（官方文档：上传文件时无须设置
     Content-Type，且直接上传裸文件而非 zip）。
  3. 轮询 ``GET {base}/extract-results/batch/{batch_id}`` -> ``data.extract_result``
     为列表，每项 ``state`` 取值 ``done|running|pending|converting|waiting-file|failed``；
     全部 ``done`` 退出，任一 ``failed`` 抛错，超时抛错。
  4. 下载 ``full_zip_url`` 的 zip，从中找名为 ``full.md`` 的成员作为 Markdown 结果。

``parse`` 返回 ``{"markdown": str, "pages": int}``，签名与 worker 调用保持不变。
"""
from __future__ import annotations

import asyncio
import io
import zipfile

import httpx

from kb_common.config import get_settings

# 走云解析的二进制格式（其余扩展名视为不支持）
BINARY_EXTS = {"pdf", "doc", "docx", "pptx", "ppt", "xlsx", "xls", "html", "htm"}
# 本地直读格式
_LOCAL_EXTS = ("txt", "md", "csv")


async def parse(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """解析文档为 ``{"markdown": str, "pages": int}``。

    txt/md/csv 走本地直读（无需 key）；二进制格式需 ``api_key`` 走 MinerU 云解析。
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in _LOCAL_EXTS:
        return {"markdown": _local_fallback(file_bytes, filename), "pages": 1}
    if ext not in BINARY_EXTS:
        raise RuntimeError(f"不支持的格式: {ext}")
    if not api_key:
        raise RuntimeError(f"解析 {ext} 需配置 MINERU_API_KEY")
    return await _cloud_parse(file_bytes, filename, api_key)


def _local_fallback(file_bytes: bytes, filename: str) -> str:
    """本地兜底：txt/md/csv 直读为 UTF-8 文本。"""
    return file_bytes.decode("utf-8", errors="ignore")


def _raise_if_api_error(payload: dict, action: str) -> None:
    """MinerU 在 HTTP 200 下用 ``code`` 字段表达业务错误，code!=0 即失败。"""
    code = payload.get("code", 0)
    if code != 0:
        raise RuntimeError(
            f"MinerU {action}失败 (code={code}): {payload.get('msg', '')}"
        )


async def _cloud_parse(file_bytes: bytes, filename: str, api_key: str) -> dict:
    """MinerU 云解析：申请上传 -> PUT 原文件 -> 轮询 -> 取 full.md。"""
    s = get_settings()
    base = s.mineru_api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. 申请预签名上传 URL
        r = await c.post(
            f"{base}/file-urls/batch",
            headers=headers,
            json={
                "enable_formula": True,
                "enable_table": True,
                "language": "ch",
                "files": [{"name": filename}],
            },
        )
        r.raise_for_status()
        payload = r.json()
        _raise_if_api_error(payload, "申请上传 URL")
        data = payload["data"]
        batch_id = data["batch_id"]
        put_url = data["file_urls"][0]

        # 2. PUT 原始文件字节（官方文档：无须设置 Content-Type，直接传裸文件）
        pr = await c.put(put_url, content=file_bytes)
        pr.raise_for_status()

        # 3. 轮询 -> 4. 下载结果 zip 取 full.md
        md = await _poll_batch(c, base, headers, batch_id)
    return {"markdown": md, "pages": 1}


async def _poll_batch(
    c: httpx.AsyncClient,
    base: str,
    headers: dict,
    batch_id: str,
    max_wait: int = 600,
    interval: int = 5,
) -> str:
    """轮询 batch 解析结果，全部 done 后下载 zip 并返回 full.md 文本。"""
    url = f"{base}/extract-results/batch/{batch_id}"
    waited = 0
    while waited <= max_wait:
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        payload = r.json()
        _raise_if_api_error(payload, "查询解析结果")
        items = payload["data"]["extract_result"]
        if items and all(it.get("state") == "done" for it in items):
            zip_url = items[0]["full_zip_url"]
            return await _fetch_md_from_zip(c, zip_url)
        if any(it.get("state") == "failed" for it in items):
            raise RuntimeError(f"MinerU 解析失败: {items}")
        await asyncio.sleep(interval)
        waited += interval
    raise RuntimeError("MinerU 解析超时")


async def _fetch_md_from_zip(c: httpx.AsyncClient, zip_url: str) -> str:
    """下载结果 zip，遍历成员找到 ``full.md`` 并返回其文本。"""
    zr = await c.get(zip_url)
    zr.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(zr.content)) as z:
        for name in z.namelist():
            if name.endswith("full.md"):
                return z.read(name).decode("utf-8", errors="ignore")
    raise RuntimeError("MinerU 结果 zip 中未找到 full.md")
