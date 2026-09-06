"""Dify 知识库相关接口：列出/新建数据集、上传文档。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Setting
from kb_common.clients import dify_client
from kb_common.config import get_settings
from app.deps import require_role

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
async def upload_dify_document(dataset_id: str,
                               file: UploadFile,
                               u=Depends(require_role("super_admin", "admin")),
                               s: AsyncSession = Depends(get_session)):
    """上传文档到指定 Dify 知识库（自动分段索引）。"""
    if not dataset_id:
        raise HTTPException(400, "请先选择目标知识库")
    base_url, api_key = await _runtime_config(s)
    _require_config(base_url, api_key)
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(400, "文件超过 15 MB 最大上传限制")
    try:
        result = await dify_client.upload_document(dataset_id, file.filename or "untitled", content)
    except Exception as e:
        raise HTTPException(502, f"Dify 上传文档失败：{e}")
    doc = result.get("document") or {}
    return {"document_id": doc.get("id"), "name": doc.get("name") or file.filename,
            "batch": result.get("batch")}
