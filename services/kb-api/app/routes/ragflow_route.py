"""RAGFlow 知识库相关接口：列出数据集/文档、新建数据集、测试连接。

与 dify_route 对称：连接凭据（base_url/api_key）从 settings 表读取并写入运行时
lru_cached settings，供 kb_common.clients.ragflow_client 使用。未配置时 fail-fast
返回可读提示，引导到「系统配置 → RAGFlow 链接配置」。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.clients import ragflow_client
from kb_common.config import get_settings
from kb_common.database import get_session
from kb_common.models import Setting
from app.deps import require_role

router = APIRouter(prefix="/api/v1/ragflow", tags=["ragflow"])


async def _effective(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key, "") or ""


def _apply_runtime_config(base_url: str, api_key: str) -> None:
    st = get_settings()
    st.ragflow_base_url = base_url
    st.ragflow_api_key = api_key


async def _runtime_config(s: AsyncSession) -> tuple[str, str]:
    base_url = (await _effective(s, "ragflow_base_url")).strip()
    api_key = (await _effective(s, "ragflow_api_key")).strip()
    _apply_runtime_config(base_url, api_key)
    return base_url, api_key


@router.get("/datasets")
async def list_ragflow_datasets(u=Depends(require_role("super_admin", "admin")),
                                s: AsyncSession = Depends(get_session)):
    """列出 RAGFlow API Key 可访问的数据集，供知识源『从 RAGFlow 选择』picker。"""
    base_url, api_key = await _runtime_config(s)
    if not base_url or not api_key:
        missing = "服务地址" if not base_url else "API Key"
        return {"items": [], "error": f"尚未配置 RAGFlow {missing}，请在『RAGFlow 链接配置』中填写并保存"}
    try:
        datasets = await ragflow_client.list_datasets()
    except ragflow_client.RagflowError as e:
        return {"items": [], "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"items": [], "error": f"无法连接 RAGFlow 服务（{e.__class__.__name__}），请检查服务地址是否正确、RAGFlow 是否已启动"}
    items = [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "description": d.get("description") or "",
            "document_count": d.get("document_count") or 0,
            "chunk_count": d.get("chunk_count") or 0,
            "chunk_method": d.get("chunk_method") or "",
            "embedding_model_name": d.get("embedding_model_name") or "",
        }
        for d in datasets
    ]
    return {"items": items}


@router.get("/datasets/{dataset_id}/documents")
async def list_ragflow_documents(dataset_id: str,
                                 u=Depends(require_role("super_admin", "admin")),
                                 s: AsyncSession = Depends(get_session)):
    """列出某 RAGFlow 数据集下的文档（含解析状态）。"""
    await _runtime_config(s)
    try:
        docs = await ragflow_client.list_documents(dataset_id)
    except ragflow_client.RagflowNotConfigured as e:
        raise HTTPException(400, str(e))
    except ragflow_client.RagflowError as e:
        raise HTTPException(502, str(e))
    return {"items": [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "run": d.get("run"),
            "progress": d.get("progress"),
            "chunk_count": d.get("chunk_count") or 0,
            "size": d.get("size") or 0,
        } for d in docs
    ]}


class DatasetIn(BaseModel):
    name: str
    chunk_method: str = "naive"          # 分块方法（实测版本字段名；旧版为 parser_id）
    embedding_model: str = ""            # 向量模型标识，如 bge-m3@Local@Xinference
    parser_config: dict[str, Any] | None = None


@router.post("/datasets")
async def create_ragflow_dataset(body: DatasetIn,
                                 u=Depends(require_role("super_admin", "admin")),
                                 s: AsyncSession = Depends(get_session)):
    """在 RAGFlow 中新建知识库（数据集）。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "知识库名称不能为空")
    await _runtime_config(s)
    try:
        d = await ragflow_client.create_dataset(name, chunk_method=body.chunk_method,
                                                embedding_model=body.embedding_model,
                                                parser_config=body.parser_config)
    except ragflow_client.RagflowNotConfigured as e:
        raise HTTPException(400, str(e))
    except ragflow_client.RagflowError as e:
        raise HTTPException(502, f"RAGFlow 新建知识库失败：{e}")
    return {"id": d.get("id"), "name": d.get("name") or name}


class TestRagflowIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    profile_id: str = ""   # 编辑态 Key 为掩码/留空时，回退该 profile 已存 Key


@router.post("/test")
async def test_ragflow(body: TestRagflowIn,
                       u=Depends(require_role("super_admin", "admin")),
                       s: AsyncSession = Depends(get_session)):
    """RAGFlow 连通性测试：编辑弹窗留空 Key 时回退已保存值（profile 或旧版单值）。"""
    base_url = body.base_url.strip()
    api_key = body.api_key.strip()
    if body.profile_id:
        from kb_common.models import RagflowProfile
        try:
            pid = uuid.UUID(body.profile_id.strip())
            row = (await s.execute(select(RagflowProfile).where(RagflowProfile.id == pid))).scalar_one_or_none()
        except ValueError:
            row = None
        if row:
            if not base_url:
                base_url = row.base_url
            if not api_key or "****" in api_key:
                api_key = row.api_key
    if not api_key or "****" in api_key:
        api_key = await _effective(s, "ragflow_api_key")
    if not base_url:
        base_url = await _effective(s, "ragflow_base_url")
    return await ragflow_client.test_connection(base_url, api_key)
