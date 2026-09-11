"""Dify 知识库相关接口：列出/新建数据集、上传文档。"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Setting
from kb_common.clients import dify_client, minio_client
from kb_common.clients.document_upload import MAX_UPLOAD_BYTES, prepare_document
from kb_common.config import get_settings
from app.deps import require_role
from app.services.collection_history import track_transfer

router = APIRouter(prefix="/api/v1/dify", tags=["dify"])

async def _effective(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key)


def _apply_runtime_config(base_url: str, api_key: str) -> None:
    """运行时可能在 settings 表中覆盖了 dify 配置，写入 settings 以便 dify_client 读取。"""
    s_obj = get_settings()
    s_obj.dify_base_url = base_url
    s_obj.dify_api_key = api_key


async def _runtime_config(s: AsyncSession) -> tuple[str, str]:
    """读取并应用运行时 Dify 配置，返回 (base_url, api_key)。"""
    base_url = (await _effective(s, "dify_base_url")).strip()
    api_key = (await _effective(s, "dify_api_key")).strip()
    _apply_runtime_config(base_url, api_key)
    return base_url, api_key


def _require_config(base_url: str, api_key: str) -> None:
    if not base_url:
        raise HTTPException(400, "尚未配置 Dify 服务地址，请先在『Dify 链接配置』中填写并保存")
    if not api_key:
        raise HTTPException(400, "尚未配置 Dify API Key，请先在『Dify 链接配置』中填写并保存")


@router.get("/datasets")
async def list_dify_datasets(u=Depends(require_role("super_admin", "admin")),
                              s: AsyncSession = Depends(get_session)):
    """列出当前 Dify API Key 可访问的数据集，供前端选择配置。"""
    base_url, api_key = await _runtime_config(s)
    if not base_url or not api_key:
        missing = "服务地址" if not base_url else "API Key"
        return {"items": [], "error": f"尚未配置 Dify {missing}，请在『Dify 链接配置』中填写并保存"}
    try:
        datasets = await dify_client.list_datasets()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        hint = "API Key 无效或无权限" if status in (401, 403) else "请检查服务地址与 API Key"
        return {"items": [], "error": f"Dify 返回 {status}：{hint}"}
    except Exception as e:
        return {"items": [], "error": f"无法连接 Dify 服务（{e.__class__.__name__}），请检查服务地址是否正确、Dify 是否已启动"}
    items = []
    for d in datasets:
        items.append({
            "id": d.get("id"),
            "name": d.get("name"),
            "description": d.get("description") or "",
            "document_count": d.get("document_count") or 0,
            "word_count": d.get("word_count") or 0,
        })
    return {"items": items}


class DatasetIn(BaseModel):
    name: str


@router.post("/datasets")
async def create_dify_dataset(body: DatasetIn,
                              u=Depends(require_role("super_admin", "admin")),
                              s: AsyncSession = Depends(get_session)):
    """在 Dify 中新建知识库（数据集）。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "知识库名称不能为空")
    base_url, api_key = await _runtime_config(s)
    _require_config(base_url, api_key)
    try:
        d = await dify_client.create_dataset(name)
    except Exception as e:
        raise HTTPException(502, f"Dify 新建知识库失败：{e}")
    return {"id": d.get("id"), "name": d.get("name") or name}


@router.post("/datasets/{dataset_id}/documents")
@track_transfer("upload")
async def upload_dify_document(dataset_id: str,
                               file: UploadFile,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    """上传文档到指定 Dify 知识库（自动分段索引）。"""
    if not dataset_id:
        raise HTTPException(400, "请先选择目标知识库")
    base_url, api_key = await _runtime_config(s)
    _require_config(base_url, api_key)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        filename, content = prepare_document(file.filename or "untitled", content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    try:
        result = await dify_client.upload_document(dataset_id, filename, content)
    except Exception as e:
        raise HTTPException(502, f"Dify 上传文档失败：{e}")
    doc = result.get("document") or {}
    return {"document_id": doc.get("id"), "name": doc.get("name") or file.filename,
            "batch": result.get("batch")}


class SyncDingTalkIn(BaseModel):
    node_id: str
    name: str
    size: int = 0


def _dingtalk_doc_url(node_id: str) -> str:
    """钉钉 wiki 节点的在线预览地址（引用来源点击跳转用）。"""
    return f"https://alidocs.dingtalk.com/i/nodes/{node_id}"


async def _save_dingtalk_mapping(s: AsyncSession, dataset_id: str, dify_document_id: str | None,
                                 node_id: str, name: str, method: str) -> None:
    """记录 Dify 文档 ↔ 钉钉节点映射，供检索召回时回填钉钉链接。"""
    if not dify_document_id:
        return
    from kb_common.models import DifyDingtalkDocMapping
    # 同一 Dify 文档可能重复同步（更新），按 dify_document_id upsert
    existing = (await s.execute(
        select(DifyDingtalkDocMapping).where(DifyDingtalkDocMapping.dify_document_id == dify_document_id)
    )).scalar_one_or_none()
    url = _dingtalk_doc_url(node_id)
    if existing:
        existing.dingtalk_node_id = node_id
        existing.dingtalk_url = url
        existing.name = name
        existing.method = method
    else:
        s.add(DifyDingtalkDocMapping(
            dify_dataset_id=dataset_id,
            dify_document_id=dify_document_id,
            dingtalk_node_id=node_id,
            dingtalk_url=url,
            name=name,
            method=method,
        ))
    await s.commit()


@router.post("/datasets/{dataset_id}/sync-dingtalk")
@track_transfer("dingtalk")
async def sync_dingtalk_file(dataset_id: str,
                              body: SyncDingTalkIn,
                              u=Depends(require_role("super_admin", "admin")),
                              s: AsyncSession = Depends(get_session)):
    """从钉钉同步文档到 Dify 知识库（按类型分流）。

    流程：
    1. 在线文档（adoc/axls/able/mind 等）：按类型导出 Office/PDF
       （adoc→docx、axls→xlsx、able→xlsx、Office 不支持的类型→pdf）；
    2. 上传的普通文件：通过 node_id 走钉钉 OSS 直链按原类型下载；
    3. 文件 <= 15MB：直接 create-by-file 上传到 Dify；
    4. 文件 > 15MB 或 create-by-file 失败：先存 OSS（Minio）备份，
       再用 MinerU 解析为 Markdown，通过 create-by-text 写入 Dify（自动分块索引）。
    成功后记录 Dify 文档 ↔ 钉钉节点映射，检索引用可跳回钉钉。
    """
    if not dataset_id:
        raise HTTPException(400, "请先选择目标知识库")
    base_url, api_key = await _runtime_config(s)
    _require_config(base_url, api_key)
    if not body.node_id:
        raise HTTPException(400, "钉钉节点 ID 为空")
    import asyncio
    import tempfile
    from pathlib import Path
    from app.services.sync.export_service import export_online_doc, online_ext_of
    from kb_common.clients import dingtalk_client

    upload_name = body.name
    online_ext = online_ext_of(body.name or "")
    if online_ext:
        # 钉钉在线文档（adoc/axls/able/mind 等）：按类型导出为 Office/PDF
        # （adoc→docx、axls→xlsx、able→xlsx、Office 不支持的类型→pdf），
        # 在线文档没有 OSS 原文件，必须走导出流程。
        try:
            with tempfile.TemporaryDirectory(prefix="dt-export-") as tmp:
                local_file = await asyncio.to_thread(
                    export_online_doc, body.node_id, body.name, Path(tmp), 360)
                content = local_file.read_bytes()
                upload_name = local_file.name  # 已带目标扩展名（xxx.docx 等）
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"导出钉钉在线文档失败：{e}")
    else:
        # 上传的普通文件：按原类型 OSS 直链下载
        try:
            await dingtalk_client.sync_runtime_config()
            if not dingtalk_client.is_configured():
                raise HTTPException(400, "钉钉 AppKey/AppSecret/操作人 未配置，请在「系统配置」中填写后重试")
            content, _dl_filename = await dingtalk_client.download_document(body.node_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"下载钉钉文件失败：{e}")
        # OSS 返回的文件名通常是无扩展名的哈希串，Dify 靠扩展名识别格式，
        # 因此优先用前端传入的原始文件名（带扩展名）。
        upload_name = body.name or _dl_filename
    if not content:
        raise HTTPException(400, "下载的文件内容为空")

    # 小文件：直接走 create-by-file
    if len(content) <= 15 * 1024 * 1024:
        try:
            result = await dify_client.upload_document(dataset_id, upload_name, content)
            doc = result.get("document") or {}
            await _save_dingtalk_mapping(s, dataset_id, doc.get("id"), body.node_id, upload_name, "file")
            return {"document_id": doc.get("id"), "name": doc.get("name") or upload_name,
                    "batch": result.get("batch"), "method": "file"}
        except Exception:
            # create-by-file 失败时降级到 OSS + MinerU + create-by-text
            return await _sync_via_mineru(s, dataset_id, upload_name, content, body.node_id)

    # 大文件：存 OSS → MinerU 解析 → create-by-text
    return await _sync_via_mineru(s, dataset_id, upload_name, content, body.node_id)


async def _sync_via_mineru(s: AsyncSession, dataset_id: str, filename: str, content: bytes,
                           node_id: str) -> dict:
    """大文件 / create-by-file 失败时的兜底流程：存 OSS → MinerU 解析 → create-by-text。"""
    # 1. 存到 OSS（Minio）作为原始备份
    obj_key = f"dingtalk-sync/{uuid.uuid4().hex}_{filename}"
    try:
        minio_client.upload_bytes(minio_client.RAW, obj_key, content)
    except Exception as e:
        raise HTTPException(502, f"文件存入 OSS 失败：{e}")

    # 2. MinerU 解析为 Markdown
    from kb_common.clients import mineru_client
    mineru_api_key = (await _effective_setting("mineru_api_key")).strip() or None
    try:
        parsed = await mineru_client.parse(content, filename, api_key=mineru_api_key)
        markdown = parsed.get("markdown") or ""
    except Exception as e:
        raise HTTPException(502, f"MinerU 解析文档失败：{e}（原文件已存 OSS：{obj_key}）")
    if not markdown or not markdown.strip():
        raise HTTPException(400, "文档解析结果为空，无法同步（原文件已存 OSS）")

    # 3. 通过 create-by-text 写入 Dify（Dify 自动分块索引，即「块拼接」）
    # doc_form / indexing_technique 由 upload_document_by_text 内部从数据集读取，保持一致
    try:
        result = await dify_client.upload_document_by_text(dataset_id, filename, markdown)
    except Exception as e:
        raise HTTPException(502, f"Dify create-by-text 上传失败：{e}（原文件已存 OSS：{obj_key}）")
    doc = result.get("document") or {}
    await _save_dingtalk_mapping(s, dataset_id, doc.get("id"), node_id, filename, "text")
    return {
        "document_id": doc.get("id"),
        "name": doc.get("name") or filename,
        "batch": result.get("batch"),
        "method": "text",
        "oss_key": obj_key,
        "note": "大文件经 MinerU 解析为 Markdown 后同步",
    }


async def _effective_setting(key: str) -> str:
    """从数据库 settings 表读取配置项（供 _sync_via_mineru 读取 mineru_api_key）。"""
    from kb_common.database import SessionLocal
    async with SessionLocal() as s:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return (row.value if row else "") or getattr(get_settings(), key, "") or ""
