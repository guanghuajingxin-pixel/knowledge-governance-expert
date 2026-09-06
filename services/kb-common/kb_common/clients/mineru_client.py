"""文档解析客户端。

解析优先级（``parse`` 统一入口，返回 ``{"markdown": str, "pages": int}``）：
  1. txt/md/csv：本地直读（无需引擎、无需 key）。
  2. PDF/DOCX/PPTX/XLSX/HTML 等二进制格式：优先走**本地 MinerU 引擎**
     （自托管 ``mineru-api`` 常驻服务，见 services/mineru，默认
     ``http://127.0.0.1:2028``，无需 key、不出内网）。
  3. 本地引擎不可用/失败时，降级到 MinerU 云 API（需 ``MINERU_API_KEY``）。

本地引擎契约（MinerU 3.x ``mineru-api``，FastAPI）：
  - ``GET  {base}/health`` 健康检查；
  - ``POST {base}/file_parse`` multipart 表单：``files``（文件，可多份）、
    ``lang_list=ch``、``backend=pipeline``、``parse_method=auto``、
    ``table_enable=true``、``return_md=true``；
  - 同步等待后返回 JSON ``{"results": {"<文件名>": {"md_content": "<markdown>"}}}``。

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
"""
from __future__ import annotations

import asyncio
import io
import logging
import zipfile

import httpx

from kb_common.config import get_settings

logger = logging.getLogger(__name__)

# 走 MinerU 解析的二进制格式（其余扩展名视为不支持）
BINARY_EXTS = {"pdf", "doc", "docx", "pptx", "ppt", "xlsx", "xls", "html", "htm"}
# 本地直读格式
_LOCAL_EXTS = ("txt", "md", "csv")

# 本地引擎解析超时：连接/健康检查快速失败，读取给足（CPU 模式大文档可能数分钟）
_ENGINE_TIMEOUT = httpx.Timeout(connect=5.0, read=900.0, write=120.0, pool=10.0)


async def parse(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """解析文档为 ``{"markdown": str, "pages": int}``。

    txt/md/csv 本地直读；二进制格式优先本地 MinerU 引擎，失败再降级云 API。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _LOCAL_EXTS:
        return {"markdown": _local_fallback(file_bytes, filename), "pages": 1}

    # 2) 本地自托管 MinerU 引擎（无需 key、不出内网）
    base = (get_settings().mineru_local_url or "").strip().rstrip("/")
    if base:
        try:
            return await _local_engine_parse(file_bytes, filename, base)
        except Exception as e:  # noqa: BLE001 - 本地引擎失败时降级云 API
            logger.warning("本地 MinerU 引擎解析失败（%s），降级云 API：%s", filename, e)

    # 3) MinerU 云 API
    if ext not in BINARY_EXTS:
        raise RuntimeError(f"不支持的格式: {ext}")
    if not api_key:
        raise RuntimeError(
            f"解析 {ext} 需要 MinerU：本地引擎未运行（services/mineru，端口 2028）"
            f"且未配置 MINERU_API_KEY"
        )
    return await _cloud_parse(file_bytes, filename, api_key)


async def is_local_alive(base: str | None = None) -> bool:
    """探测本地 MinerU 引擎是否可用（供健康检查/启动脚本使用）。"""
    base = (base or get_settings().mineru_local_url or "").strip().rstrip("/")
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)) as c:
            r = await c.get(f"{base}/health")
            return r.status_code == 200
    except Exception:
        return False


async def _local_engine_parse(file_bytes: bytes, filename: str, base: str) -> dict:
    """调用自托管 ``mineru-api`` 的 ``/file_parse`` 同步解析，取 md_content。"""
    async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT) as c:
        h = await c.get(f"{base}/health")
        if h.status_code != 200:
            raise RuntimeError(f"mineru-api 健康检查失败: HTTP {h.status_code}")

        files = {"files": (filename, file_bytes, "application/octet-stream")}
        data = {
            "lang_list": "ch",
            "backend": "pipeline",
            "parse_method": "auto",
            "table_enable": "true",
            "formula_enable": "false",
            "return_md": "true",
        }
        r = await c.post(f"{base}/file_parse", files=files, data=data)
        if r.status_code != 200:
            raise RuntimeError(f"mineru-api /file_parse 返回 {r.status_code}: {r.text[:300]}")
        payload = r.json()

    results = payload.get("results") or {}
    md = ""
    for _name, res in results.items():
        md = (res or {}).get("md_content") or md
    if not md or not md.strip():
        raise RuntimeError("mineru-api 未返回有效 md_content（可能文档无文本层且 OCR 失败）")
    return {"markdown": md, "pages": 1}


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
