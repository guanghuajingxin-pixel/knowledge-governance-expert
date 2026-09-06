"""DeerFlow 2.0 QA Sidecar 的内部接口（服务间调用，X-Internal-Token 鉴权）。

- GET  /api/v1/agent/bootstrap           向 sidecar 提供 LLM 引导配置
- POST /api/v1/internal/kb/retrieve       供 sidecar 的 knowledge_search 工具调用 Dify 检索
- POST /api/v1/internal/dingtalk/search   供 sidecar 的 dingtalk_search 工具调用钉钉知识库检索
- POST /api/v1/internal/dingtalk/content  供 sidecar 的 dingtalk_read_doc 工具读取钉钉文档正文
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session

router = APIRouter(prefix="/api/v1", tags=["agent-internal"])

_DEFAULT_TOKEN = "kge-internal-dev-token"

# dws CLI 路径（钉钉 Workspace CLI，用于读取钉钉在线文档正文与下载钉盘文件）
_DWS_BIN = os.getenv("DWS_BIN", str(Path(__file__).resolve().parents[4] / "tools" / "dws" / "dws"))
_DWS_TIMEOUT = 120.0
# dws 并发保护：多会话并行问答时会同时读钉钉文档，钉钉 API 限频下未处理的
# dws 失败会变成 500。按既定约定全局限流（并发≤3 + 0.4s 节流）并对瞬时失败重试 1 次。
_DWS_SEM = asyncio.Semaphore(3)
_DWS_MIN_INTERVAL = 0.4
_last_dws_ts = 0.0


async def _verify_internal_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")):
    expected = os.getenv("KB_INTERNAL_TOKEN", _DEFAULT_TOKEN)
    if x_internal_token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


async def _effective_setting(s: AsyncSession, key: str) -> str:
    """DB settings 表优先，回退环境变量/默认 settings。"""
    from kb_common.config import get_settings
    from kb_common.models import Setting

    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key, "") or ""


class RetrieveIn(BaseModel):
    query: str
    dataset_ids: list[str] | None = None
    top_k: int = 8


@router.post("/internal/kb/retrieve", dependencies=[Depends(_verify_internal_token)])
async def internal_kb_retrieve(body: RetrieveIn, s: AsyncSession = Depends(get_session)):
    """企业知识库检索：供 DeerFlow knowledge_search 工具调用。"""
    from kb_common.clients import dify_client
    from kb_common.config import get_settings

    settings = get_settings()
    # 运行时写入 lru_cached settings（与问答链路一致）
    settings.dify_base_url = await _effective_setting(s, "dify_base_url")
    settings.dify_api_key = await _effective_setting(s, "dify_api_key")

    dataset_ids = body.dataset_ids or []
    if not dataset_ids:
        dataset_ids = [d.strip() for d in (await _effective_setting(s, "dify_dataset_ids") or "").split(",") if d.strip()]

    try:
        hits = await dify_client.retrieve(dataset_ids, body.query, top_k=body.top_k)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"dify retrieve failed: {e.__class__.__name__}: {e}") from e

    return {"results": hits, "total": len(hits)}


class DingTalkSearchIn(BaseModel):
    query: str
    top_k: int = 10


@router.post("/internal/dingtalk/search", dependencies=[Depends(_verify_internal_token)])
async def internal_dingtalk_search(body: DingTalkSearchIn):
    """钉钉知识库关键词检索：供 DeerFlow dingtalk_search 工具调用。

    基于已缓存的钉钉知识库文件列表做关键词模糊匹配（文件名 + 目录路径）。
    钉钉开放平台无语义检索 API，仅支持按元数据匹配。
    """
    from app.routes.knowledge_center import _dingtalk_cache, _trigger_dingtalk_refresh
    from kb_common.clients import dingtalk_client

    # 确保钉钉配置已加载
    try:
        await dingtalk_client.sync_runtime_config()
        if not dingtalk_client.is_configured():
            return {"results": [], "total": 0, "error": "钉钉未配置"}
    except Exception as e:  # noqa: BLE001
        return {"results": [], "total": 0, "error": f"钉钉配置加载失败：{e}"}

    # 触发后台刷新（首次或过期时）
    _trigger_dingtalk_refresh(force=False)
    cached_files = _dingtalk_cache.get("files") or []

    if not cached_files:
        return {
            "results": [],
            "total": 0,
            "loading": _dingtalk_cache.get("loading", False),
            "error": _dingtalk_cache.get("error", ""),
        }

    # 关键词分词匹配（所有词都必须出现在文件名或目录路径中）
    keywords = [k.strip().lower() for k in body.query.split() if k.strip()]
    matched = []
    for f in cached_files:
        name = (f.get("name") or "").lower()
        path = (f.get("directory_path") or "").lower()
        combined = f"{name} {path}"
        if all(kw in combined for kw in keywords):
            matched.append(f)

    # 按名称相关度排序（关键词在名称中的位置越前越相关）
    matched.sort(key=lambda f: (f.get("name") or "").lower().find(keywords[0]) if keywords else 999)

    top = matched[: body.top_k]
    results = [
        {
            "title": f.get("name") or "",
            "directory": f.get("directory_path") or "/",
            "workspace": f.get("workspace_name") or "",
            "url": f.get("url") or "",
            "node_id": f.get("node_id") or "",
            "extension": f.get("extension") or "",
            "creator": f.get("creator_name") or f.get("creator_id") or "",
            "created_at": f.get("created_at") or "",
        }
        for f in top
    ]
    return {"results": results, "total": len(results), "matched_total": len(matched)}


@router.get("/agent/bootstrap", dependencies=[Depends(_verify_internal_token)])
async def agent_bootstrap(s: AsyncSession = Depends(get_session)):
    """向 DeerFlow sidecar 提供 LLM 引导配置。"""
    base_url = await _effective_setting(s, "llm_base_url")
    api_key = await _effective_setting(s, "llm_api_key")
    model = await _effective_setting(s, "llm_model")
    if not api_key or not model:
        raise HTTPException(status_code=409, detail="LLM not configured in system settings")

    from app.services.agent.config import load_agent_config

    agent_cfg = await load_agent_config(s)
    return {
        "model": model,
        "base_url": base_url or "https://api.deepseek.com/v1",
        "api_key": api_key,
        "temperature": float(agent_cfg.get("temperature", 0.7)),
        "max_tokens": int(agent_cfg.get("max_tokens", 4096)),
        "agent_name": agent_cfg.get("agent_name", "杰克百晓生"),
    }


# ---------------------------------------------------------------------------
# 钉钉文档正文读取（dws CLI）
# ---------------------------------------------------------------------------

class DingTalkContentIn(BaseModel):
    node_id: str
    extension: str = ""
    title: str = ""


# 可由 dws doc read 直读 Markdown 的在线/文本类文档扩展名
_DT_ONLINE_EXTS = {"adoc", "md", "markdown", "txt", "html", "htm"}
# 可下载后本地解析的办公文档
_DT_OFFICE_EXTS = {"doc", "docx", "pdf", "xlsx", "xls", "ppt", "pptx", "csv", "rtf", "wps"}


def _dingtalk_cached_files():
    """获取钉钉缓存文件列表（触发加载快照，不等待后台刷新）。"""
    from app.routes.knowledge_center import _dingtalk_cache, _load_dingtalk_snapshot
    _load_dingtalk_snapshot()
    return _dingtalk_cache.get("files") or [], _dingtalk_cache.get("loading", False)


class DingTalkBrowseIn(BaseModel):
    action: str = "map"          # map=知识目录地图；list=列出目录下文件
    directory: str = ""          # list：目录关键词（模糊匹配 directory_path 或 workspace）
    top_k: int = 30


@router.post("/internal/dingtalk/browse", dependencies=[Depends(_verify_internal_token)])
async def internal_dingtalk_browse(body: DingTalkBrowseIn):
    """钉钉知识库目录浏览：供 DeerFlow dingtalk_browse 工具调用。

    - action=map：返回知识库→目录结构（2 级）及文档数/在线文档数，
      供智能体预判问题答案可能在哪个目录；
    - action=list：列出匹配目录下的文档，在线文档（adoc/md/txt）优先，
      返回 node_id/title/extension，供 dingtalk_read_doc 逐篇读取。
    """
    from app.routes.knowledge_center import _trigger_dingtalk_refresh
    _trigger_dingtalk_refresh(force=False)
    files, loading = _dingtalk_cached_files()
    if not files:
        return {"results": [], "loading": loading,
                "error": "钉钉文件列表加载中" if loading else "钉钉知识库暂无数据"}

    if body.action == "map":
        return _browse_map(files)
    return _browse_list(files, body.directory, body.top_k)


def _browse_map(files: list[dict]) -> dict:
    """聚合知识库目录地图：workspace → 一级/二级目录 → 文档计数。"""
    workspaces: dict[str, dict] = {}
    for f in files:
        ext = (f.get("extension") or "").lower()
        if ext not in _DT_ONLINE_EXTS and ext not in _DT_OFFICE_EXTS:
            continue  # 跳过音视频/图片/压缩包等非文档
        ws = f.get("workspace_name") or "未分组"
        path = (f.get("directory_path") or "/").strip("/")
        parts = [p for p in path.split("/") if p][:2]  # 最多 2 级目录
        ws_entry = workspaces.setdefault(ws, {"name": ws, "docs": 0, "online_docs": 0, "dirs": {}})
        online = ext in _DT_ONLINE_EXTS
        ws_entry["docs"] += 1
        ws_entry["online_docs"] += 1 if online else 0
        if parts:
            dkey = "/" + "/".join(parts)
            d = ws_entry["dirs"].setdefault(dkey, {"path": dkey, "docs": 0, "online_docs": 0})
            d["docs"] += 1
            d["online_docs"] += 1 if online else 0

    ws_list = sorted(workspaces.values(), key=lambda w: -w["docs"])[:12]
    for ws in ws_list:
        ws["dirs"] = sorted(ws["dirs"].values(), key=lambda d: -d["docs"])[:15]
    return {"action": "map", "workspaces": ws_list, "total_docs": sum(w["docs"] for w in workspaces.values())}


def _browse_list(files: list[dict], directory: str, top_k: int) -> dict:
    """列出匹配目录下的文档；在线文档优先，办公文档其次。"""
    kw = (directory or "").strip().lower()
    online, office = [], []
    for f in files:
        ext = (f.get("extension") or "").lower()
        if ext not in _DT_ONLINE_EXTS and ext not in _DT_OFFICE_EXTS:
            continue
        path = (f.get("directory_path") or "").lower()
        ws = (f.get("workspace_name") or "").lower()
        if kw and kw not in path and kw not in ws:
            continue
        item = {
            "title": f.get("name") or "",
            "node_id": f.get("node_id") or "",
            "extension": ext,
            "directory": f.get("directory_path") or "/",
            "workspace": f.get("workspace_name") or "",
            "url": f.get("url") or "",
            "online": ext in _DT_ONLINE_EXTS,
        }
        (online if ext in _DT_ONLINE_EXTS else office).append(item)

    # 在线文档优先；同类按修改时间（files 顺序近似）
    results = online + office
    return {"action": "list", "directory": directory, "total": len(results),
            "results": results[:max(1, min(top_k, 50))]}


async def _run_dws(args: list[str]) -> dict:
    """运行 dws CLI 并解析 JSON 输出（全局并发≤3 + 0.4s 节流 + 瞬时失败重试 1 次）。"""
    global _last_dws_ts
    if not Path(_DWS_BIN).exists():
        raise RuntimeError(f"dws CLI 不存在: {_DWS_BIN}")
    async with _DWS_SEM:
        for attempt in (1, 2):
            gap = _last_dws_ts + _DWS_MIN_INTERVAL - time.monotonic()
            if gap > 0:
                await asyncio.sleep(gap)
            _last_dws_ts = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                _DWS_BIN, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DWS_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                if attempt == 2:
                    raise RuntimeError("dws 调用超时")
                continue
            out = stdout.decode("utf-8", errors="ignore").strip()
            err = ""
            if not out:
                err = f"dws 无输出: {stderr.decode('utf-8', errors='ignore')[:200]}"
            else:
                try:
                    return json.loads(out)
                except json.JSONDecodeError:
                    err = f"dws 输出非 JSON: {out[:300]}"
            if attempt == 2:
                raise RuntimeError(err)
            await asyncio.sleep(1.0)  # 限频/瞬时失败退避后重试


def _dingtalk_doc_url(node_id: str) -> str:
    """从钉钉文件缓存按 node_id 查网页链接（无缓存/未命中返回空串）。"""
    from app.routes.knowledge_center import _dingtalk_cache
    for f in _dingtalk_cache.get("files") or []:
        if (f.get("node_id") or "") == node_id:
            return f.get("url") or ""
    return ""


@router.post("/internal/dingtalk/content", dependencies=[Depends(_verify_internal_token)])
async def internal_dingtalk_content(body: DingTalkContentIn, s: AsyncSession = Depends(get_session)):
    """读取钉钉文档正文内容：供 DeerFlow dingtalk_read_doc 工具调用。

    - 在线文档（adoc/markdown/md）：`dws doc read` 直接返回 Markdown
    - 二进制文件（docx/pdf/xlsx 等）：`dws drive download` 下载后用 MinerU/本地解析器转 Markdown
    - 返回携带 `url`（钉钉网页链接），供前端把答案中的《文档名》转为可点击的源文档预览链接
    """
    ext = (body.extension or "").lower()
    node_id = body.node_id.strip()
    if not node_id:
        raise HTTPException(status_code=400, detail="node_id 不能为空")

    doc_url = _dingtalk_doc_url(node_id)

    # 1) 在线文档：直接读 Markdown
    if ext in ("adoc", "markdown", "md", ""):
        try:
            data = await _run_dws(["doc", "read", "--node", node_id, "-f", "json"])
            if data.get("success") is False or "error" in data:
                # 可能是二进制文件（extension 为空时兜底）
                pass
            else:
                return {
                    "title": data.get("title") or body.title,
                    "content": data.get("markdown") or "",
                    "format": "markdown",
                    "node_id": node_id,
                    "url": doc_url,
                }
        except Exception:
            # 在线文档读取失败，降级到下载解析
            pass

    # 2) 二进制文件：下载到临时目录，再解析
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            await _run_dws([
                "drive", "download",
                "--node", node_id,
                "--output", tmpdir,
                "--overwrite",
                "-f", "json",
            ])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"钉钉文档下载失败：{e}") from e

        files = list(Path(tmpdir).iterdir())
        if not files:
            raise HTTPException(status_code=502, detail="钉钉文档下载后未找到文件")
        local_file = files[0]
        file_bytes = local_file.read_bytes()
        filename = body.title or local_file.name

        # 二进制办公文档：MinerU 为首要解析引擎（本地自托管 mineru-api → 云 API），
        # 支持 pptx/ppt/pdf/doc/docx/xls/xlsx 的版面/表格/扫描件 OCR；
        # 引擎不可用或返回空时，降级到本地即时解析（python-pptx/docx/openpyxl/pdfplumber）。
        mineru_error: str | None = None
        try:
            from kb_common.clients import mineru_client
            mineru_api_key = await _effective_setting(s, "mineru_api_key") or None
            parsed = await mineru_client.parse(file_bytes, filename, api_key=mineru_api_key)
            md = (parsed.get("markdown") or "").strip()
            if md:
                return {
                    "title": body.title or local_file.name,
                    "content": md,
                    "format": "markdown",
                    "node_id": node_id,
                    "url": doc_url,
                    "engine": "mineru",
                }
            mineru_error = "MinerU 返回空内容"
        except Exception as e:  # noqa: BLE001 - 引擎失败时尝试本地兜底
            mineru_error = f"{e.__class__.__name__}: {e}"

        local_md = _local_parse(file_bytes, filename)
        if local_md and local_md.strip():
            return {
                "title": body.title or local_file.name,
                "content": local_md,
                "format": "markdown",
                "node_id": node_id,
                "url": doc_url,
                "engine": "local",
            }

        raise HTTPException(
            status_code=502,
            detail=f"文档解析失败（MinerU 与本地解析均未取得正文）：{mineru_error}",
        )


def _local_parse(file_bytes: bytes, filename: str) -> str | None:
    """本地即时解析常见文本/办公文档为 Markdown（无需外部服务）。

    - txt/md/csv：UTF-8 直读；
    - docx：正文段落 + 表格 + 文本框（w:txbxContent）；
    - ppt/pptx：逐页抽取形状文本、表格、组合形状与备注；
    - xlsx/xls：各工作表表格化；pdf：pdfplumber 抽文本层。
    不支持的格式或解析异常返回 None，由调用方降级 MinerU。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    from io import BytesIO
    try:
        if ext in ("txt", "md", "markdown", "csv"):
            return file_bytes.decode("utf-8", errors="ignore")

        if ext == "docx":
            import docx as docx_lib  # python-docx
            doc = docx_lib.Document(BytesIO(file_bytes))
            parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
            # 表格
            for tbl in doc.tables:
                rows = []
                for row in tbl.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        rows.append("| " + " | ".join(cells) + " |")
                if rows:
                    parts.append("\n".join(rows))
            # 文本框/形状内文字（python-docx 默认不抽 w:txbxContent）
            try:
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for txbx in doc.element.body.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}txbxContent"
                ):
                    txt = "".join(t.text or "" for t in txbx.iter(ns["w"] + "t")).strip()
                    if txt:
                        parts.append(txt)
            except Exception:
                pass
            return "\n".join(parts) if parts else None

        if ext in ("pptx", "ppt"):
            from pptx import Presentation  # python-pptx

            prs = Presentation(BytesIO(file_bytes))

            def _shape_text(shape) -> list[str]:
                out: list[str] = []
                # 组合形状：递归
                if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
                    for sub in shape.shapes:
                        out.extend(_shape_text(sub))
                    return out
                if getattr(shape, "has_text_frame", False) and shape.text_frame:
                    t = shape.text_frame.text.strip()
                    if t:
                        out.append(t)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                        if any(cells):
                            out.append("| " + " | ".join(cells) + " |")
                return out

            slides_md: list[str] = []
            for idx, slide in enumerate(prs.slides, 1):
                lines: list[str] = [f"## 幻灯片 {idx}"]
                for shape in slide.shapes:
                    lines.extend(_shape_text(shape))
                try:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        lines.append(f"> 备注：{notes}")
                except Exception:
                    pass
                body = "\n".join(l for l in lines if l and l != f"## 幻灯片 {idx}")
                if body:
                    slides_md.append(f"## 幻灯片 {idx}\n{body}")
            return "\n\n".join(slides_md) if slides_md else None

        if ext in ("xlsx", "xls"):
            from openpyxl import load_workbook
            wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
            lines: list[str] = []
            for ws in wb.worksheets:
                lines.append(f"## {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(cells):
                        lines.append("| " + " | ".join(cells) + " |")
            return "\n".join(lines)

        if ext == "pdf":
            import pdfplumber
            text_parts: list[str] = []
            with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n".join(text_parts) if text_parts else None
    except Exception:
        return None
    return None
