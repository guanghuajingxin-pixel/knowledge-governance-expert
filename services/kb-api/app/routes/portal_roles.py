"""统一门户角色管理路由：角色 CRUD + 菜单注册表（仅管理员）。

护栏沿用账号管理口径：仅 super_admin/admin 可访问；
角色分配（给用户）仍在账号管理接口完成。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import require_role
from app.services import portal_roles
from app.services.audit import write_audit
from app.services.menu_registry import menu_tree
from kb_common.database import get_session

router = APIRouter(prefix='/api/v1/portal', tags=['门户角色管理'])
admin = require_role('super_admin', 'admin')


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    menu_permissions: list[str] | None = None

    @field_validator('code', 'name')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()

    @field_validator('description')
    @classmethod
    def strip_description(cls, value):
        return (value or '').strip() or None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    menu_permissions: list[str] | None = None

    @field_validator('name')
    @classmethod
    def nonempty(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('description')
    @classmethod
    def strip_description(cls, value):
        # 空串表示清除描述；不传（None）表示不变
        return value.strip() if isinstance(value, str) else value


class RoleOut(BaseModel):
    id: str
    code: str
    name: str
    description: str
    is_system: bool
    menu_permissions: list[str] | None
    user_count: int
    created_at: str | None
    updated_at: str | None


@router.get('/menus')
async def list_menus(u=Depends(admin)):
    return {'groups': menu_tree()}


@router.get('/roles', response_model=list[RoleOut])
async def list_roles(u=Depends(admin), s: AsyncSession = Depends(get_session)):
    return await portal_roles.list_roles(s)


@router.post('/roles', response_model=RoleOut, status_code=201)
async def create_role(body: RoleCreate, request: Request,
                      u=Depends(admin), s: AsyncSession = Depends(get_session)):
    result = await portal_roles.create_role(
        s, code=body.code, name=body.name,
        description=body.description, menu_permissions=body.menu_permissions)
    await write_audit(s, actor_id=u.id, action='portal_role_create', target_type='portal_role',
                      target_id=result['id'],
                      detail={'code': body.code, 'name': body.name,
                              'menu_permissions': body.menu_permissions},
                      request=request)
    return result


@router.put('/roles/{role_id}', response_model=RoleOut)
async def update_role(role_id: UUID, body: RoleUpdate, request: Request,
                      u=Depends(admin), s: AsyncSession = Depends(get_session)):
    # 区分「未提交 menu_permissions」（保持不变）与「显式 null」（恢复全部菜单）
    menus = (body.menu_permissions
             if 'menu_permissions' in body.model_fields_set else portal_roles.UNSET)
    result = await portal_roles.update_role(
        s, role_id, name=body.name, description=body.description,
        menu_permissions=menus)
    await write_audit(s, actor_id=u.id, action='portal_role_update', target_type='portal_role',
                      target_id=str(role_id),
                      detail=body.model_dump(exclude_unset=True), request=request)
    return result


@router.delete('/roles/{role_id}', status_code=204)
async def delete_role(role_id: UUID, request: Request,
                      u=Depends(admin), s: AsyncSession = Depends(get_session)):
    await portal_roles.delete_role(s, role_id)
    await write_audit(s, actor_id=u.id, action='portal_role_delete', target_type='portal_role',
                      target_id=str(role_id), detail={}, request=request)
