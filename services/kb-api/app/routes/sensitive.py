"""敏感信息管理：知识应用侧的敏感内容登记 CRUD。

支持企业维护敏感信息（关键词/号码等），列表呈现内容、类型、添加时间、状态，
提供添加/编辑/删除与启停；敏感数据仅管理员可见可管（数据安全要求）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import SensitiveItem
from app.deps import require_role

router = APIRouter(prefix="/api/v1/sensitive-items", tags=["sensitive-items"])

TYPES = ("phone", "id_card", "bank_card", "email", "custom")

# 敏感信息属企业机密数据：列表与增删改均限管理员（数据安全要求）
ADMIN_ONLY = [Depends(require_role("super_admin", "admin"))]


class SensitiveItemOut(BaseModel):
    id: int
    content: str
    type: str
    description: str
    enabled: bool
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class SensitiveItemCreate(BaseModel):
    content: str = Field(max_length=500)
    type: str = "custom"
    description: str = ""
    enabled: bool = True


class SensitiveItemUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=500)
    type: str | None = None
    description: str | None = None
    enabled: bool | None = None


@router.get("", response_model=list[SensitiveItemOut], dependencies=ADMIN_ONLY)
async def list_sensitive_items(
    type: str | None = Query(None, description="按类型过滤"),
    keyword: str | None = Query(None, description="按内容模糊搜索"),
    s: AsyncSession = Depends(get_session),
):
    """敏感信息列表（仅 super_admin/admin 可见）。"""
    q = select(SensitiveItem)
    if type:
        if type not in TYPES:
            raise HTTPException(422, f"不支持的类型：{type}")
        q = q.where(SensitiveItem.type == type)
    if keyword and keyword.strip():
        q = q.where(SensitiveItem.content.ilike(f"%{keyword.strip()}%"))
    q = q.order_by(SensitiveItem.id.desc())
    return (await s.execute(q)).scalars().all()


@router.post("", response_model=SensitiveItemOut, dependencies=ADMIN_ONLY)
async def create_sensitive_item(
    payload: SensitiveItemCreate,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """登记敏感信息（同内容不可重复）。"""
    if not payload.content.strip():
        raise HTTPException(422, "敏感信息内容不能为空")
    if payload.type not in TYPES:
        raise HTTPException(422, f"不支持的类型：{payload.type}")
    dup = (await s.execute(select(SensitiveItem).where(
        SensitiveItem.content == payload.content.strip(),
    ))).scalars().first()
    if dup:
        raise HTTPException(409, "该敏感信息已存在，请勿重复添加")
    item = SensitiveItem(
        content=payload.content.strip(),
        type=payload.type,
        description=(payload.description or "").strip(),
        enabled=payload.enabled,
        created_by=u.username,
    )
    s.add(item)
    await s.commit()
    await s.refresh(item)
    return item


@router.put("/{item_id}", response_model=SensitiveItemOut, dependencies=ADMIN_ONLY)
async def update_sensitive_item(
    item_id: int,
    payload: SensitiveItemUpdate,
    s: AsyncSession = Depends(get_session),
):
    """更新敏感信息（内容/类型/备注/启停）。"""
    item = await s.get(SensitiveItem, item_id)
    if item is None:
        raise HTTPException(404, "敏感信息不存在")
    data = payload.model_dump(exclude_unset=True)
    if "content" in data:
        if not (data["content"] or "").strip():
            raise HTTPException(422, "敏感信息内容不能为空")
        data["content"] = data["content"].strip()
        dup = (await s.execute(select(SensitiveItem).where(
            SensitiveItem.content == data["content"],
            SensitiveItem.id != item_id,
        ))).scalars().first()
        if dup:
            raise HTTPException(409, "该敏感信息已存在，请勿重复添加")
    if "type" in data and data["type"] not in TYPES:
        raise HTTPException(422, f"不支持的类型：{data['type']}")
    for key, value in data.items():
        setattr(item, key, value)
    await s.commit()
    await s.refresh(item)
    return item


@router.delete("/{item_id}", dependencies=ADMIN_ONLY)
async def delete_sensitive_item(
    item_id: int,
    s: AsyncSession = Depends(get_session),
):
    """删除敏感信息。"""
    item = await s.get(SensitiveItem, item_id)
    if item is None:
        raise HTTPException(404, "敏感信息不存在")
    await s.delete(item)
    await s.commit()
    return {"ok": True}
