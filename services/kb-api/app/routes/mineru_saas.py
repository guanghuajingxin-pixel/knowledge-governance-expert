"""MinerU 解析引擎 · 云端 SaaS 适配器（统一契约 → mineru.net V4 契约）。

解析引擎页与外部调用方按统一契约（见 mineru_contract.py）发起请求：uploads 三步
上传、parse/jobs 异步任务、files/{id}/content 拉产物。MinerU 云端 SaaS（默认
https://mineru.net/api/v4）是另一套契约：file-urls/batch 申请预签名上传 URL →
PUT 裸文件 → extract-results/batch 轮询 → 结果 zip 内取 full.md / content_list.json。
本适配器把统一契约翻译为 V4，调用方（X-Mineru-Base=cloud）无感切换，页面交互
（上传/队列/结果预览）完全复用。

API Key 不经手前端：复用模型配置页的 mineru_api_key（settings 表 > .env，脱敏存储），
mineru_api_url 可覆盖 SaaS 地址。

档位语义映射（speed/balanced/quality → pipeline/vlm）见 mineru_contract.resolve_tier。

状态为进程内临时态：上传会话 / 任务注册表 / 结果 zip 缓存存内存与临时目录，
kb-api 重启后清空（SaaS 侧结果仍按 batch_id 保留，测试台重新提交即可）。
"""
from __future__ import annotations

import io
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import HTTPException, Response
from sqlalchemy import select

from kb_common.config import get_settings
from kb_common.database import SessionLocal
from kb_common.models import Setting

from app.routes.mineru_contract import SEMANTIC_TIERS, resolve_tier

# 统一契约状态 → 前端 JobStatus（见 ParserCustomTab.vue type JobStatus）
_SAAS_STATE_MAP = {
    "waiting-file": "queued",
    "pending": "queued",
    "converting": "running",
    "running": "running",
    "done": "completed",
    "failed": "failed",
}

_TMP_DIR = Path(tempfile.gettempdir()) / "kge-mineru-saas"
_UPLOADS: dict[str, dict] = {}  # upload_id -> {id, filename, mime, size, path, done}
_JOBS: dict[str, dict] = {}  # batch_id -> 任务注册表（见 _register_job）
_ZIPS: dict[tuple[str, int], bytes] = {}  # (batch_id, 文件序号) -> 结果 zip 字节缓存

_HTTP = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)

ENGINE_LABEL = "MinerU Cloud SaaS"


async def _effective_conn() -> tuple[str, str]:
    """SaaS 地址与 Key：settings 表覆盖 > .env（get_settings）。"""
    base = (get_settings().mineru_api_url or "").strip().rstrip("/")
    key = (get_settings().mineru_api_key or "").strip()
    async with SessionLocal() as s:
        rows = (await s.execute(select(Setting).where(Setting.key.in_(["mineru_api_url", "mineru_api_key"])))).scalars().all()
    for row in rows:
        v = (row.value or "").strip()
        if not v:
            continue
        if row.key == "mineru_api_url":
            base = v.rstrip("/")
        elif row.key == "mineru_api_key":
            key = v
    return base or "https://mineru.net/api/v4", key


def _api_error(payload: dict, action: str) -> None:
    """MinerU 云 API 用 HTTP 200 + code 字段表达业务错误。"""
    if payload.get("code", 0) != 0:
        raise HTTPException(502, f"MinerU 云 API {action}失败 (code={payload.get('code')}): {payload.get('msg', '')}")


async def _saas_request(method: str, url: str, *, key: str | None = None, **kw) -> dict:
    async with httpx.AsyncClient(timeout=_HTTP) as c:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = await c.request(method, url, headers=headers, **kw)
    if r.status_code != 200:
        raise HTTPException(502, f"MinerU 云 API 返回 HTTP {r.status_code}: {r.text[:300]}")
    payload = r.json()
    _api_error(payload, action=url.rsplit("/", 1)[-1])
    return payload


# ---------- 契约端点（由 mineru_route 显式路由调用） ----------

async def saas_health() -> dict:
    _base, key = await _effective_conn()
    if not key:
        raise HTTPException(503, "未配置 MinerU API Key：请在 模型配置 页填写并保存（云端 SaaS 模式）")
    return {
        "version": "cloud-v4 (SaaS)",
        "features": {"output_formats": ["markdown", "structured_json"]},
        "capabilities": {
            "engine": "cloud",
            "engine_label": ENGINE_LABEL,
            "tiers": ["speed", "balanced", "quality"],
            "output_formats": ["markdown", "structured_json"],
            "cancelable": False,
            "page_range": True,
            "max_file_mb": 200,
        },
    }


def saas_tiers() -> dict:
    return {"data": [
        {"id": t["id"], "description": t["description"], "raw_tier": t["cloud"]}
        for t in SEMANTIC_TIERS
    ]}


async def saas_create_upload(meta: dict) -> dict:
    filename = (meta.get("filename") or "unnamed").strip()
    upload_id = uuid.uuid4().hex[:16]
    _UPLOADS[upload_id] = {
        "id": upload_id,
        "filename": filename,
        "mime": meta.get("mime_type") or "application/octet-stream",
        "size": int(meta.get("bytes") or 0),
        "path": _TMP_DIR / f"{upload_id}.bin",
        "done": False,
    }
    return {"id": upload_id}


async def saas_put_upload_content(upload_id: str, body: bytes) -> dict:
    up = _UPLOADS.get(upload_id)
    if not up:
        raise HTTPException(404, f"上传会话不存在（可能服务已重启）：{upload_id}")
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    up["path"].write_bytes(body)
    return {"ok": True}


async def saas_complete_upload(upload_id: str) -> dict:
    up = _UPLOADS.get(upload_id)
    if not up:
        raise HTTPException(404, f"上传会话不存在（可能服务已重启）：{upload_id}")
    if not up["path"].exists():
        raise HTTPException(400, "未上传文件内容（缺少 PUT content 步骤）")
    up["done"] = True
    up["size"] = up["path"].stat().st_size
    return {"id": upload_id, "file": {"id": upload_id, "filename": up["filename"]}}


def _register_job(batch_id: str, tier: str, raw_tier: str, files: list[dict]) -> dict:
    job = {
        "batch_id": batch_id,
        "tier": tier,
        "raw_tier": raw_tier,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "files": files,  # [{file_id, name, state, output_files:{}}]
    }
    _JOBS[batch_id] = job
    return job


def _job_brief(job: dict) -> dict:
    return {
        "job_id": job["batch_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "tier": job["tier"],
        "raw_tier": job["raw_tier"],
        "progress": {
            "completed": sum(1 for f in job["files"] if f["state"] == "completed"),
            "failed": sum(1 for f in job["files"] if f["state"] == "failed"),
            "total": len(job["files"]),
        },
        "files": [
            {"name": f["name"], "output_files": f["output_files"]}
            for f in job["files"]
        ],
    }


async def saas_create_job(payload: dict) -> dict:
    tier, raw_tier = resolve_tier(payload.get("tier") or "balanced", "cloud")
    ocr_mode = payload.get("ocr_mode") or "auto"
    base, key = await _effective_conn()
    if not key:
        raise HTTPException(400, "未配置 MinerU API Key，请先在模型配置页填写并保存")

    entries = []
    for item in payload.get("files") or []:
        upload_id = ((item.get("source") or {}).get("file_id") or "").strip()
        up = _UPLOADS.get(upload_id)
        if not up or not up.get("done"):
            raise HTTPException(400, f"file_id 无效或未完成上传：{upload_id or '(空)'}")
        entries.append({"up": up, "name": up["filename"],
                        "page_range": (item.get("page_range") or "").strip() or None})
    if not entries:
        raise HTTPException(400, "任务未包含任何文件")

    # 申请预签名上传 URL（一个 batch 携带全部文件）
    saas_files = []
    for e in entries:
        f: dict = {"name": e["name"], "is_ocr": ocr_mode == "ocr"}
        if e["page_range"]:
            f["page_ranges"] = e["page_range"]
        saas_files.append(f)
    data = (await _saas_request(
        "POST", f"{base}/file-urls/batch", key=key,
        json={"enable_formula": True, "enable_table": True, "language": "ch",
              "model_version": raw_tier, "files": saas_files},
    ))["data"]
    batch_id, put_urls = data["batch_id"], data["file_urls"]
    if len(put_urls) != len(entries):
        raise HTTPException(502, f"SaaS 返回上传 URL 数量不符：{len(put_urls)} != {len(entries)}")

    # PUT 裸文件字节到预签名 URL（官方文档：无须设置 Content-Type）
    async with httpx.AsyncClient(timeout=_HTTP) as c:
        for e, put_url in zip(entries, put_urls):
            r = await c.put(put_url, content=e["up"]["path"].read_bytes())
            if r.status_code >= 300:
                raise HTTPException(502, f"上传文件到 MinerU 云端失败：HTTP {r.status_code}")

    job = _register_job(batch_id, tier, raw_tier, [
        {"file_id": e["up"]["id"], "name": e["name"],
         "state": "running", "output_files": {}}
        for e in entries
    ])
    return _job_brief(job)


def saas_list_jobs() -> dict:
    rows = [_job_brief(j) for j in _JOBS.values()]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"data": [
        {"job_id": r["job_id"], "status": r["status"], "created_at": r["created_at"], "file_count": len(r["files"])}
        for r in rows
    ]}


async def saas_get_job(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"任务不存在（云端任务注册表随服务重启清空）：{job_id}")
    base, key = await _effective_conn()
    payload = await _saas_request("GET", f"{base}/extract-results/batch/{job_id}", key=key)
    items = ((payload.get("data") or {}).get("extract_result")) or []
    for idx, f in enumerate(job["files"]):
        it = items[idx] if idx < len(items) else {}
        f["state"] = _SAAS_STATE_MAP.get(it.get("state") or "", "running")
        f["error"] = it.get("err_msg") or ""
        if f["state"] == "completed" and it.get("full_zip_url"):
            f["zip_url"] = it["full_zip_url"]  # 供结果包整体下载（md+images）
            await _ensure_zip(job_id, idx, it["full_zip_url"])
            f["output_files"] = _output_files(job_id, idx, f["name"])
        elif f["state"] != "completed":
            f["output_files"] = {}
    states = [f["state"] for f in job["files"]]
    if states and all(s == "completed" for s in states):
        job["status"] = "completed"
    elif "failed" in states and "completed" in states:
        job["status"] = "partial"
    elif "failed" in states:
        job["status"] = "failed"
    else:
        job["status"] = "running"
    return _job_brief(job)


def saas_delete_job(job_id: str) -> None:
    raise HTTPException(409, "云端 SaaS 任务暂不支持取消，可等待其完成或忽略")


async def saas_result_zip(job_id: str, idx: int) -> Response:
    """原始结果 zip（full.md + images/ + content_list.json），解压即得完整 markdown。"""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"任务不存在（云端任务注册表随服务重启清空）：{job_id}")
    if not (0 <= idx < len(job["files"])):
        raise HTTPException(404, f"文件序号越界：{idx}")
    url = job["files"][idx].get("zip_url")
    if not url:
        raise HTTPException(409, "该文件尚未完成解析，无结果包可下载")
    data = await _ensure_zip(job_id, idx, url)
    return Response(content=data, media_type="application/zip")


# ---------- 结果 zip 缓存与产物下载 ----------

async def _ensure_zip(batch_id: str, idx: int, zip_url: str) -> bytes:
    """每个文件有独立结果 zip，按 (batch_id, idx) 缓存避免多文件 batch 互相覆盖。"""
    key = (batch_id, idx)
    if key in _ZIPS:
        return _ZIPS[key]
    async with httpx.AsyncClient(timeout=_HTTP) as c:
        r = await c.get(zip_url)
    if r.status_code != 200:
        raise HTTPException(502, f"下载解析结果 zip 失败：HTTP {r.status_code}")
    _ZIPS[key] = r.content
    return r.content


def _zip_members(key: tuple[str, int]) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(_ZIPS[key]))


def _output_files(batch_id: str, idx: int, name: str) -> dict:
    """统一契约 output_files 形状：markdown 必给；云端 zip 无 middle.json，以
    content_list.json（结构化段落 JSON）填充 structured_json 槽位供 JSON 预览。
    file_id = batch::idx::成员名（成员可为产物文档，也可为 images/*.jpg 等图片，
    由 GET /v1/files/{file_id}/content 按 Content-Type 返回）。"""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    out: dict = {}
    try:
        zf = _zip_members((batch_id, idx))
        names = zf.namelist()
    except Exception:
        return out

    def find(suffix: str) -> str | None:
        cands = [n for n in names if n.endswith(suffix)]
        return sorted(cands, key=len)[0] if cands else None

    md = find("full.md")
    if md:
        out["markdown"] = {"file_id": f"{batch_id}::{idx}::{md}", "bytes": zf.getinfo(md).file_size,
                           "name": f"{stem}.md"}
    cl = find("content_list.json")
    if cl:
        out["structured_json"] = {"file_id": f"{batch_id}::{idx}::{cl}", "bytes": zf.getinfo(cl).file_size,
                                  "name": f"{stem}_content_list.json"}
    return out


# 产物成员扩展名 → 响应 Content-Type
_MEMBER_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


async def saas_file_content(file_id: str) -> Response:
    try:
        batch_id, idx_s, member = file_id.split("::", 2)
        key = (batch_id, int(idx_s))
    except (ValueError, TypeError):
        raise HTTPException(400, f"云端产物 file_id 格式非法：{file_id[:60]}")
    if key not in _ZIPS:
        raise HTTPException(404, "结果 zip 缓存不存在（服务重启后请重新提交任务）")
    try:
        zf = _zip_members(key)
        data = zf.read(member)
    except KeyError:
        raise HTTPException(404, f"结果 zip 中不存在成员：{member}")
    lower = member.lower()
    media = next((t for ext, t in _MEMBER_TYPES.items() if lower.endswith(ext)),
                 "application/octet-stream")
    return Response(content=data, media_type=media)
