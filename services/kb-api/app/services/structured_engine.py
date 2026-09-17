"""结构化处理引擎：MinerU 解析通道 + JSON 路径映射 + 动态建表写入。

解析通道（页内可选，均产出归一化 content 块数组）：
  - kit_v1  ：本地 mineru-kit V1 API（默认 127.0.0.1:8010），inline 上传 +
              output_formats=structured_content/markdown，异步 job 轮询取件；
  - cloud_v4：MinerU 云 API（mineru.net/api/v4），申请上传 URL → PUT → 轮询 →
              下载结果 zip，取 *_content_list.json 与 full.md。

映射模型：
  - row_source：行源 JSON 路径（相对解析结果根，默认 ``content``，即每个解析块一行）；
  - columns：[{name, type, path, const}]，path 为行内相对路径（支持 a.b[0].c），
    const 为常量（支持占位符 {file_name} {task_id} {engine} {parsed_at}）。

写入目标：本项目共享 PostgreSQL 的独立 schema ``structured``，按列定义动态
CREATE TABLE IF NOT EXISTS；表已存在时补缺列后追加（append-friendly）。
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.config import get_settings

logger = logging.getLogger(__name__)

_JOB_TIMEOUT = 900.0
_POLL_INTERVAL = 2.0

# 支持的列类型 → DDL
COLUMN_TYPES: dict[str, str] = {
    "text": "TEXT",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "jsonb": "JSONB",
}

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


# ============================================================
# 解析通道
# ============================================================
async def kit_v1_available() -> bool:
    base = (get_settings().structured_kit_base_url or "").strip().rstrip("/")
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)) as c:
            r = await c.get(f"{base}/v1/health")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown",
    "txt": "text/plain",
}


async def _kit_upload_file(c: httpx.AsyncClient, base: str, file_bytes: bytes, filename: str) -> str:
    """OpenAI 兼容上传三步：create → PUT 裸字节 → complete，返回 file_id。

    inline source 有 max_inline_bytes（默认 1MB）限制，大文件必须走上传流。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    r = await c.post(
        f"{base}/v1/uploads",
        json={
            "filename": filename,
            "bytes": len(file_bytes),
            "mime_type": _MIME_BY_EXT.get(ext, "application/octet-stream"),
            "purpose": "parse",
        },
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"mineru-kit 创建上传失败: HTTP {r.status_code} {r.text[:200]}")
    upload_id = (r.json() or {}).get("id")
    if not upload_id:
        raise RuntimeError("mineru-kit 创建上传未返回 id")

    pu = await c.put(
        f"{base}/v1/uploads/{upload_id}/content",
        content=file_bytes,
        headers={"Content-Type": "application/octet-stream"},
    )
    if pu.status_code not in (200, 201, 204):
        raise RuntimeError(f"mineru-kit 上传字节失败: HTTP {pu.status_code} {pu.text[:200]}")

    cr = await c.post(f"{base}/v1/uploads/{upload_id}/complete")
    if cr.status_code not in (200, 201):
        raise RuntimeError(f"mineru-kit 完成上传失败: HTTP {cr.status_code} {cr.text[:200]}")
    # complete 返回的是 UploadResponse（id 仍为 upload id）；真正的 File id 在嵌套 file 对象里
    data = cr.json() or {}
    file_id = (data.get("file") or {}).get("id")
    if not file_id:
        gr = await c.get(f"{base}/v1/uploads/{upload_id}")
        file_id = ((gr.json() or {}).get("file") or {}).get("id")
    if not file_id:
        raise RuntimeError("mineru-kit 完成上传后未取到 file id")
    return file_id


async def parse_with_kit_v1(file_bytes: bytes, filename: str, tier: str, ocr_mode: str) -> dict:
    """本地 mineru-kit V1：上传文件 → 提交 job → 轮询 → 取 structured_content / markdown。"""
    base = (get_settings().structured_kit_base_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("未配置 mineru-kit V1 地址（STRUCTURED_KIT_BASE_URL）")
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=60.0, write=300.0, pool=10.0)) as c:
        file_id = await _kit_upload_file(c, base, file_bytes, filename)
        payload = {
            "files": [{"source": {"type": "file_id", "file_id": file_id}}],
            "tier": tier or "standard",
            "ocr_mode": ocr_mode or "auto",
            "output_formats": ["structured_content", "markdown"],
        }
        r = await c.post(f"{base}/v1/parse/jobs", json=payload)
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"mineru-kit 提交解析失败: HTTP {r.status_code} {r.text[:200]}")
        job_id = (r.json() or {}).get("job_id")
        if not job_id:
            raise RuntimeError("mineru-kit 未返回 job_id")

        job: dict = {}
        deadline = asyncio.get_event_loop().time() + _JOB_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            jr = await c.get(f"{base}/v1/parse/jobs/{job_id}")
            if jr.status_code != 200:
                continue
            job = jr.json() or {}
            if job.get("status") in ("completed", "partial", "failed", "canceled"):
                break
        status = job.get("status")
        if status not in ("completed", "partial"):
            raise RuntimeError(f"mineru-kit 解析未成功（status={status}）")

        files = job.get("files") or []
        if not files:
            raise RuntimeError("mineru-kit job 无文件结果")
        outputs = files[0].get("output_files") or {}
        content = await _fetch_kit_output(c, base, outputs, "structured_content")
        markdown = await _fetch_kit_output(c, base, outputs, "markdown", as_text=True)

    return {
        "content": _normalize_content(content),
        "markdown": markdown or "",
        "meta": {"engine": "kit_v1", "tier": tier, "ocr_mode": ocr_mode, "remote_job_id": job_id},
    }


async def _fetch_kit_output(c: httpx.AsyncClient, base: str, outputs: dict, key: str, as_text: bool = False):
    ref = outputs.get(key) or {}
    file_id = ref.get("file_id")
    if not file_id:
        return None
    r = await c.get(f"{base}/v1/files/{file_id}/content")
    if r.status_code != 200:
        return None
    if as_text:
        try:
            data = r.json()
            return data if isinstance(data, str) else r.text
        except Exception:  # noqa: BLE001
            return r.text
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return None


async def parse_with_cloud_v4(file_bytes: bytes, filename: str) -> dict:
    """MinerU 云 API v4：申请上传 URL → PUT 裸文件 → 轮询 → 下载 zip 取 content_list。"""
    s = get_settings()
    base = (s.mineru_api_url or "").rstrip("/")
    key = (s.mineru_api_key or "").strip()
    if not key:
        raise RuntimeError("未配置 MINERU_API_KEY，无法走 MinerU 云 API 通道")
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=10.0)) as c:
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
        if r.status_code != 200:
            raise RuntimeError(f"MinerU 云申请上传失败: HTTP {r.status_code} {r.text[:200]}")
        data = (r.json() or {}).get("data") or {}
        if data.get("code") not in (0, None) and (r.json() or {}).get("code") not in (0, None):
            raise RuntimeError(f"MinerU 云申请上传业务错误: {r.text[:200]}")
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []
        if not batch_id or not file_urls:
            raise RuntimeError("MinerU 云未返回 batch_id/file_urls")

        pu = await c.put(file_urls[0], content=file_bytes)
        if pu.status_code not in (200, 201):
            raise RuntimeError(f"MinerU 云上传文件失败: HTTP {pu.status_code}")

        deadline = asyncio.get_event_loop().time() + _JOB_TIMEOUT
        result_item: dict = {}
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL * 2)
            qr = await c.get(f"{base}/extract-results/batch/{batch_id}", headers=headers)
            if qr.status_code != 200:
                continue
            items = ((qr.json() or {}).get("data") or {}).get("extract_result") or []
            if not items:
                continue
            result_item = items[0]
            state = result_item.get("state")
            if state == "done":
                break
            if state == "failed":
                raise RuntimeError(f"MinerU 云解析失败: {result_item.get('err_msg', '')}")
        if result_item.get("state") != "done":
            raise RuntimeError("MinerU 云解析超时")

        zip_url = result_item.get("full_zip_url")
        if not zip_url:
            raise RuntimeError("MinerU 云未返回 full_zip_url")
        zr = await c.get(zip_url)
        if zr.status_code != 200:
            raise RuntimeError(f"MinerU 云结果包下载失败: HTTP {zr.status_code}")

    content: Any = None
    markdown = ""
    with zipfile.ZipFile(io.BytesIO(zr.content)) as zf:
        for name in zf.namelist():
            low = name.lower()
            if low.endswith("content_list.json") and content is None:
                content = json.loads(zf.read(name).decode("utf-8"))
            if low.endswith("full.md"):
                markdown = zf.read(name).decode("utf-8", errors="ignore")
    return {
        "content": _normalize_content(content),
        "markdown": markdown,
        "meta": {"engine": "cloud_v4", "remote_job_id": batch_id},
    }


def _norm_block(b: dict, page_idx: Any = None) -> dict:
    """单块归一：补 page_idx；MinerU 4.x 的文本在 ``content`` 字段，别名到 ``text``。"""
    nb = dict(b)
    if page_idx is not None:
        nb.setdefault("page_idx", page_idx)
    if "text" not in nb and isinstance(nb.get("content"), str):
        nb["text"] = nb["content"]
    return nb


def _normalize_content(raw: Any) -> list:
    """把 MinerU 结构化输出归一为扁平块数组（list of dict）。

    兼容两种形状：
      - MinerU 4.x structured_content：``{pages:[{page_idx, blocks:[...]}], ...}``；
      - 旧版 content_list：``[{type, text, page_idx, ...}, ...]``。
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        pages = raw.get("pages")
        if isinstance(pages, list):
            out: list[dict] = []
            for p in pages:
                if not isinstance(p, dict):
                    continue
                pidx = p.get("page_idx")
                for b in p.get("blocks") or []:
                    if isinstance(b, dict):
                        out.append(_norm_block(b, pidx))
            return out
        for key in ("content", "content_list", "blocks", "items"):
            v = raw.get(key)
            if isinstance(v, list):
                return [_norm_block(x) for x in v if isinstance(x, dict)]
        return [raw]
    if isinstance(raw, list):
        # 元素都带 blocks → 视为 pages 数组；否则视为块数组
        if raw and all(isinstance(x, dict) and isinstance(x.get("blocks"), list) for x in raw):
            out = []
            for p in raw:
                pidx = p.get("page_idx")
                for b in p.get("blocks") or []:
                    if isinstance(b, dict):
                        out.append(_norm_block(b, pidx))
            return out
        return [_norm_block(x) for x in raw if isinstance(x, dict)]
    return []


# ============================================================
# JSON 路径 & 映射
# ============================================================
_PATH_SEG_RE = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


def get_path(obj: Any, path: str) -> Any:
    """支持 ``a.b[0].c`` 的点号 + 下标路径取值；取不到返回 None。"""
    if not path:
        return None
    cur = obj
    for m in _PATH_SEG_RE.finditer(path):
        if cur is None:
            return None
        key, idx = m.group(1), m.group(2)
        if key is not None:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        else:
            i = int(idx)
            if isinstance(cur, list) and 0 <= i < len(cur):
                cur = cur[i]
            else:
                return None
    return cur


def resolve_row_source(root: Any, row_source: str) -> list:
    """行源：默认 content；路径取到数组即按元素成行，非数组包成单行。"""
    path = (row_source or "content").strip()
    if path in ("", "$", "root"):
        target = root
    else:
        target = get_path(root, path)
    if target is None:
        return []
    if isinstance(target, list):
        return target
    return [target]


def _coerce(value: Any, col_type: str) -> Any:
    if value is None:
        return None
    t = col_type or "text"
    try:
        if t == "text":
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)
        if t in ("integer", "bigint"):
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return int(value)
            s = str(value).strip()
            return int(float(s)) if s else None
        if t == "numeric":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            s = str(value).strip()
            return float(s) if s else None
        if t == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "y", "t")
        if t == "date":
            d = _parse_dt(value)
            return d.date() if d else None
        if t == "timestamp":
            return _parse_dt(value)
        if t == "jsonb":
            return value
    except Exception:  # noqa: BLE001 - 单值转换失败置空，不阻断整批
        return None
    return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    s = str(value).strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.split("+")[0].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


_CONST_PLACEHOLDERS = ("{file_name}", "{task_id}", "{engine}", "{parsed_at}")


def build_rows(root: Any, row_source: str, columns: list, ctx: dict) -> tuple[list[dict], list[str]]:
    """按行源 + 列映射生成行数据；返回 (rows, warnings)。"""
    rows_elements = resolve_row_source(root, row_source)
    warnings: list[str] = []
    rows: list[dict] = []
    cols = [c for c in (columns or []) if c.get("name")]
    for i, elem in enumerate(rows_elements):
        row: dict = {}
        for col in cols:
            name = col["name"]
            const = col.get("const")
            if const is not None and str(const).strip() != "":
                val: Any = str(const)
                for ph in _CONST_PLACEHOLDERS:
                    val = val.replace(ph, str(ctx.get(ph.strip("{}"), "")))
            else:
                val = _coerce(get_path(elem, col.get("path") or ""), col.get("type") or "text")
            row[name] = val
        rows.append(row)
    if not rows:
        warnings.append(f"行源「{row_source or 'content'}」未取到任何数组元素，预览/写入将为空")
    return rows, warnings


# ============================================================
# 写入目标库（连接串可配置：settings 表 > 环境变量 > 系统 database_url）
# ============================================================
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession, create_async_engine

_WRITE_ENGINES: dict[str, Any] = {}


def normalize_async_db_url(url: str) -> str:
    """把各种 PG 连接串写法归一到 asyncpg 驱动。"""
    u = (url or "").strip()
    if u.startswith("postgresql+asyncpg://"):
        return u
    if u.startswith("postgresql+psycopg://"):
        return u.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    if u.startswith("postgresql://"):
        return u.replace("postgresql://", "postgresql+asyncpg://", 1)
    if u.startswith("postgres://"):
        return u.replace("postgres://", "postgresql+asyncpg://", 1)
    return u


def mask_db_url(url: str) -> str:
    """掩码连接串中的密码：postgresql://user:****@host:port/db。"""
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1****\2", url or "")


@asynccontextmanager
async def write_session(url: str):
    """写入目标库会话（独立连接池，按 URL 缓存引擎）。"""
    key = normalize_async_db_url(url)
    if not key:
        raise RuntimeError("未配置写入目标库连接串")
    engine = _WRITE_ENGINES.get(key)
    if engine is None:
        engine = create_async_engine(key, pool_pre_ping=True, pool_size=3, max_overflow=2)
        _WRITE_ENGINES[key] = engine
    session = _AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()


async def test_db_url(url: str) -> dict:
    """连通性测试：SELECT 1 + 版本 + structured schema 可建性检查。"""
    try:
        async with write_session(url) as s:
            row = (await s.execute(text("SELECT version()"))).scalar()
            await s.execute(text("CREATE SCHEMA IF NOT EXISTS structured"))
            await s.commit()
        return {"ok": True, "message": str(row)[:120]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}


# ============================================================
# 建表 & 写入（目标库 structured schema）
# ============================================================
def sanitize_ident(name: str, kind: str) -> str:
    v = (name or "").strip().lower()
    if not _IDENT_RE.match(v):
        raise ValueError(f"{kind}名「{name}」不合法：仅允许小写字母/数字/下划线，且不以数字开头")
    return v


async def ensure_table(session: AsyncSession, table: str, columns: list) -> None:
    valid = [c for c in (columns or []) if c.get("name")]
    if not valid:
        raise ValueError("至少需要一列映射")
    cols = [sanitize_ident(c["name"], "列") for c in valid]
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS structured"))
    col_defs = ",\n  ".join(
        f'"{name}" {COLUMN_TYPES.get((col.get("type") or "text"), "TEXT")}'
        for name, col in zip(cols, valid)
    )
    await session.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS structured."{table}" (\n'
            f"  id BIGSERIAL PRIMARY KEY,\n"
            f"  _task_id UUID,\n"
            f"  _written_at TIMESTAMPTZ DEFAULT now(),\n"
            f"  {col_defs}\n)"
        )
    )
    # 表已存在：补缺列（append-friendly）
    for name, col in zip(cols, valid):
        ctype = COLUMN_TYPES.get((col.get("type") or "text"), "TEXT")
        await session.execute(
            text(f'ALTER TABLE structured."{table}" ADD COLUMN IF NOT EXISTS "{name}" {ctype}')
        )
    await session.commit()


async def insert_rows(session: AsyncSession, table: str, columns: list, rows: list[dict], task_id: str) -> int:
    cols = [sanitize_ident(c["name"], "列") for c in (columns or []) if c.get("name")]
    if not rows or not cols:
        return 0
    named = ", ".join(f'"{c}"' for c in cols)
    params_expr = ", ".join(f":{c}" for c in cols)
    sql = text(f'INSERT INTO structured."{table}" (_task_id, {named}) VALUES (:_task_id, {params_expr})')
    params = [{**{c: r.get(c) for c in cols}, "_task_id": task_id} for r in rows]
    await session.execute(sql, params)
    await session.commit()
    return len(params)


async def list_structured_tables(session: AsyncSession) -> list[dict]:
    r = await session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema='structured' ORDER BY table_name")
    )
    tables = [row[0] for row in r.fetchall()]
    out: list[dict] = []
    for t in tables:
        cnt = await session.execute(text(f'SELECT count(*) FROM structured."{t}"'))
        out.append({"table": t, "rows": cnt.scalar() or 0})
    return out
