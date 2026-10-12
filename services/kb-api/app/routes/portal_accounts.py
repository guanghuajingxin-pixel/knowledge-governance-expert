"""统一门户账号管理（仅管理员）：账号生命周期与角色分配全部经由身份中心完成。

护栏：
- 不能停用 / 删除 / 改动自己的角色（防自锁与自我提权）；
- 仅超级管理员可分配 super_admin 角色，且 admin 不可修改 super_admin 账号（防提权）。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import require_role
from app.services import portal_accounts
from app.services.audit import write_audit
from kb_common.database import get_session

router = APIRouter(prefix='/api/v1/portal/accounts', tags=['门户账号管理'])
admin = require_role('super_admin', 'admin')
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'


class AccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    role: str = 'viewer'
    password: str = Field(min_length=1, max_length=128)
    temporary: bool = True

    @field_validator('username', 'name')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()

    @field_validator('email')
    @classmethod
    def email_or_none(cls, value):
        value = (value or '').strip()
        return value or None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    # email 传空串表示清除邮箱；不传（None）表示不变
    email: str | None = Field(default=None, max_length=200)
    role: str | None = None
    enabled: bool | None = None

    @field_validator('name')
    @classmethod
    def nonempty(cls, value):
        return AccountCreate.nonempty(value) if value is not None else None

    @field_validator('email')
    @classmethod
    def strip_email(cls, value):
        return value.strip() if isinstance(value, str) else value


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    temporary: bool = True


class AccountOut(BaseModel):
    id: str
    username: str
    name: str
    email: str | None
    enabled: bool
    created_at: str | None
    roles: list[str]


class AccountListOut(BaseModel):
    items: list[AccountOut]
    page: int
    page_size: int
    has_more: bool


def _ensure_assignable(role: str | None, actor) -> None:
    if role == 'super_admin' and actor.role != 'super_admin':
        raise HTTPException(403, '仅超级管理员可分配超级管理员角色')


def _ensure_writable(target: dict, actor) -> None:
    if 'super_admin' in target['roles'] and actor.role != 'super_admin':
        raise HTTPException(403, '管理员不可修改超级管理员账号')


def _ensure_not_self(target: dict, actor, message: str) -> None:
    if target['username'] == actor.username:
        raise HTTPException(400, message)


@router.get('', response_model=AccountListOut)
async def list_accounts(response: Response, search: str = '', page: int = 1,
                        page_size: int = DEFAULT_PAGE_SIZE, u=Depends(admin)):
    _no_cache(response)
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    # Keycloak 用户列表无总数：多取一条判断是否还有下一页
    items = await portal_accounts.list_accounts(
        search=search.strip(), first=(page - 1) * page_size, max_results=page_size + 1)
    return {'items': items[:page_size], 'page': page, 'page_size': page_size,
            'has_more': len(items) > page_size}


@router.post('', response_model=AccountOut, status_code=201)
async def create_account(body: AccountCreate, request: Request, response: Response,
                         u=Depends(admin), s: AsyncSession = Depends(get_session)):
    _no_cache(response)
    _ensure_assignable(body.role, u)
    result = await portal_accounts.create_account(
        username=body.username, name=body.name, email=body.email, role=body.role,
        password=body.password, temporary=body.temporary)
    await write_audit(s, actor_id=u.id, action='portal_account_create', target_type='portal_account',
                      target_id=result['id'],
                      detail={'username': result['username'], 'name': body.name,
                              'email': body.email, 'role': body.role, 'temporary': body.temporary},
                      request=request)
    return result


@router.patch('/{user_id}', response_model=AccountOut)
async def update_account(user_id: UUID, body: AccountUpdate, request: Request, response: Response,
                         u=Depends(admin), s: AsyncSession = Depends(get_session)):
    _no_cache(response)
    target = await portal_accounts.get_account(user_id)
    _ensure_writable(target, u)
    if (body.role is not None or body.enabled is False):
        _ensure_not_self(target, u, '不能对当前登录账号执行此操作')
    _ensure_assignable(body.role, u)
    result = await portal_accounts.update_account(user_id, **body.model_dump(exclude_none=True))
    await write_audit(s, actor_id=u.id, action='portal_account_update', target_type='portal_account',
                      target_id=str(user_id), detail=body.model_dump(exclude_none=True), request=request)
    return result


@router.put('/{user_id}/password', status_code=204)
async def reset_password(user_id: UUID, body: PasswordReset, request: Request,
                         u=Depends(admin), s: AsyncSession = Depends(get_session)):
    target = await portal_accounts.get_account(user_id)
    _ensure_writable(target, u)
    await portal_accounts.reset_password(user_id, password=body.password, temporary=body.temporary)
    await write_audit(s, actor_id=u.id, action='portal_account_reset_password', target_type='portal_account',
                      target_id=str(user_id), detail={'temporary': body.temporary}, request=request)


@router.delete('/{user_id}', status_code=204)
async def delete_account(user_id: UUID, request: Request,
                         u=Depends(admin), s: AsyncSession = Depends(get_session)):
    target = await portal_accounts.get_account(user_id)
    _ensure_writable(target, u)
    _ensure_not_self(target, u, '不能删除当前登录账号')
    await portal_accounts.delete_account(user_id)
    await write_audit(s, actor_id=u.id, action='portal_account_delete', target_type='portal_account',
                      target_id=str(user_id), detail={'username': target['username']}, request=request)
