"""知识库（检索抽象层）：统一知识库镜像登记 CRUD。

与「知识源管理」（推送路径定义）相互独立：本路由管理的知识库仅用于智能体检索，
只登记 platform + dataset_id 镜像引用，不支持导入/解析新文档；
检索时按 platform 由抽象层（dify/ragflow 客户端）决定各自检索策略。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import KnowledgeLibrary
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1/knowledge-libraries", tags=["knowledge-library"])

PLATFORMS = ("dify", "ragflow")


class KnowledgeLibraryOut(BaseModel):
    id: int
    name: str
    platform: str
    dataset_id: str
    description: str
    enabled: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeLibraryCreate(BaseModel):
    name: str = Field(max_length=200)
    platform: str
    dataset_id: str = Field(max_length=128)
    description: str = ""
    enabled: bool = True


class KnowledgeLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    enabled: bool | None = None


@router.get("", response_model=list[KnowledgeLibraryOut])
async def list_knowledge_libraries(
    enabled_only: bool = Query(False, description="只返回已启用的知识库"),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """知识库镜像列表：问答页/统一检索等所有「选择知识库」处从此接口取数。"""
    q = select(KnowledgeLibrary)
    if enabled_only:
        q = q.where(KnowledgeLibrary.enabled == True)  # noqa: E712
    q = q.order_by(KnowledgeLibrary.platform, KnowledgeLibrary.id.desc())
    return (await s.execute(q)).scalars().all()


@router.post("", response_model=KnowledgeLibraryOut,
             dependencies=[Depends(require_role("super_admin", "admin"))])
async def create_knowledge_library(
    payload: KnowledgeLibraryCreate,
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """登记知识库镜像（仅 dify | ragflow；同平台同 dataset_id 不可重复）。"""
    if payload.platform not in PLATFORMS:
        raise HTTPException(422, f"不支持的平台类型：{payload.platform}（仅支持 dify / ragflow）")
    if not payload.name.strip():
        raise HTTPException(422, "知识库名称不能为空")
    if not payload.dataset_id.strip():
        raise HTTPException(422, "数据集 ID 不能为空")
    dup = (await s.execute(select(KnowledgeLibrary).where(
        KnowledgeLibrary.platform == payload.platform,
        KnowledgeLibrary.dataset_id == payload.dataset_id.strip(),
    ))).scalars().first()
    if dup:
        raise HTTPException(409, f"该平台的此知识库已登记为「{dup.name}」，请勿重复添加")
    lib = KnowledgeLibrary(
        name=payload.name.strip(),
        platform=payload.platform,
        dataset_id=payload.dataset_id.strip(),
        description=(payload.description or "").strip(),
        enabled=payload.enabled,
    )
    s.add(lib)
    await s.commit()
    await s.refresh(lib)
    return lib


@router.put("/{library_id}", response_model=KnowledgeLibraryOut,
            dependencies=[Depends(require_role("super_admin", "admin"))])
async def update_knowledge_library(
    library_id: int,
    payload: KnowledgeLibraryUpdate,
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """更新知识库镜像（改名/描述/启停；platform 与 dataset_id 不可改，需删后重加）。"""
    lib = await s.get(KnowledgeLibrary, library_id)
    if lib is None:
        raise HTTPException(404, "知识库不存在")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        if not (data["name"] or "").strip():
            raise HTTPException(422, "知识库名称不能为空")
        data["name"] = data["name"].strip()
    for key, value in data.items():
        setattr(lib, key, value)
    await s.commit()
    await s.refresh(lib)
    return lib


@router.delete("/{library_id}",
               dependencies=[Depends(require_role("super_admin", "admin"))])
async def delete_knowledge_library(
    library_id: int,
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """删除知识库镜像（不影响引擎平台上的原库）。"""
    lib = await s.get(KnowledgeLibrary, library_id)
    if lib is None:
        raise HTTPException(404, "知识库不存在")
    await s.delete(lib)
    await s.commit()
    return {"ok": True}
