"""统一门户角色管理：角色定义与菜单权限存本地 PG；Keycloak 模式同步 client role。

护栏：
- 系统角色不可删除、code 不可改、仅菜单权限/描述可改；
- 有用户占用的角色不可删除；
- code 正则 ^[a-z][a-z0-9_]{1,49}$，且不得与系统角色重名。
"""
import logging
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.config import get_settings
from kb_common.models import PortalRole, User

from .menu_registry import KNOWN_MENU_KEYS

logger = logging.getLogger(__name__)
SYSTEM_ROLE_CODES = ("super_admin", "admin", "editor", "viewer")
SYSTEM_ROLE_ORDER = {code: i for i, code in enumerate(SYSTEM_ROLE_CODES)}
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
#: 哨兵：update_role 的 menu_permissions 参数未提交（保持不变）——与 None（显式恢复全部菜单）区分
UNSET: object = object()


def validate_code(code: str) -> None:
    if not CODE_PATTERN.match(code):
        raise HTTPException(400, '角色标识须为 2-50 位小写字母开头的小写字母/数字/下划线')
    if code in SYSTEM_ROLE_CODES:
        raise HTTPException(400, '角色标识不能与系统角色重名')


def validate_menu_permissions(menu_permissions: list | None) -> list[str] | None:
    """None=未配置（全部菜单）；非空列表=白名单（key 须在注册表内）。"""
    if menu_permissions is None:
        return None
    if not isinstance(menu_permissions, list) or not menu_permissions:
        raise HTTPException(400, '菜单权限至少选择一个菜单，或留空表示全部菜单')
    unknown = [k for k in menu_permissions if k not in KNOWN_MENU_KEYS]
    if unknown:
        raise HTTPException(400, f'未知的菜单标识：{unknown[0]}')
    return list(menu_permissions)


def public_role(row: PortalRole, user_count: int = 0) -> dict:
    return {
        'id': str(row.id),
        'code': row.code,
        'name': row.name,
        'description': row.description or '',
        'is_system': bool(row.is_system),
        'menu_permissions': list(row.menu_permissions) if row.menu_permissions is not None else None,
        'user_count': user_count,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    }


async def get_role(s: AsyncSession, role_id: UUID) -> PortalRole:
    row = await s.get(PortalRole, role_id)
    if row is None:
        raise HTTPException(404, '角色不存在')
    return row


async def user_count(s: AsyncSession, code: str) -> int:
    """local 模式按本地 users.role 计数；keycloak 模式按 client role 映射计数（含自动建档用户）。"""
    local_count = (await s.execute(
        select(func.count()).select_from(User).where(User.role == code))).scalar() or 0
    if get_settings().auth_provider != 'keycloak':
        return int(local_count)
    try:
        from .keycloak_admin import admin_session
        from .portal_accounts import _resource_id
        async with admin_session() as admin:
            rid = await _resource_id(admin)
            rows = await admin.call('GET', f'clients/{rid}/roles/{code}/users',
                                    params={'first': 0, 'max': 100})
            kc_count = len([r for r in rows if not r.get('serviceAccountClientLink')])
            return max(int(local_count), kc_count)
    except HTTPException as exc:
        if exc.status_code == 404:
            # client role 漂移（Keycloak 侧被手工删除）：本地行仍在即按本地计数
            return int(local_count)
        raise


async def list_roles(s: AsyncSession) -> list[dict]:
    rows = (await s.execute(select(PortalRole))).scalars().all()
    counts = {code: (await s.execute(
        select(func.count()).select_from(User).where(User.role == code))).scalar() or 0
        for code in {r.code for r in rows}}
    # 系统角色固定在前（按既定顺序），自定义角色按创建时间
    def _key(row: PortalRole):
        order = SYSTEM_ROLE_ORDER.get(row.code)
        return (0, order) if order is not None else (1, row.created_at)
    return [public_role(row, int(counts.get(row.code, 0)))
            for row in sorted(rows, key=_key)]


async def create_role(s: AsyncSession, *, code: str, name: str,
                      description: str | None, menu_permissions: list | None) -> dict:
    validate_code(code)
    menu_permissions = validate_menu_permissions(menu_permissions)
    exists = (await s.execute(select(PortalRole).where(
        PortalRole.code == code))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, '角色标识已存在，请更换后重试')
    row = PortalRole(code=code, name=name, description=description,
                     is_system=False, menu_permissions=menu_permissions)
    s.add(row)
    await s.commit()
    if get_settings().auth_provider == 'keycloak':
        try:
            await _sync_create_client_role(code)
        except Exception:
            # 补偿：client role 创建失败即回收本地半成品角色（与账号创建同策略）
            await s.delete(row)
            await s.commit()
            raise
    return public_role(row, 0)


async def _sync_create_client_role(code: str) -> None:
    """Keycloak 模式：同步创建 client role 供分配；409（已存在）视为漂移收编。"""
    from .keycloak_admin import admin_session
    from .portal_accounts import _resource_id
    try:
        async with admin_session() as admin:
            rid = await _resource_id(admin)
            await admin.call('POST', f'clients/{rid}/roles', json={'name': code})
    except HTTPException as exc:
        if exc.status_code == 409:
            return
        raise


async def update_role(s: AsyncSession, role_id: UUID, *, name: str | None,
                      description: str | None,
                      menu_permissions: object = UNSET) -> dict:
    row = await get_role(s, role_id)
    if row.is_system:
        # 系统角色：名称/描述/代码只读，仅菜单权限可改
        if name is not None and name != row.name:
            raise HTTPException(400, '系统角色的名称不可修改')
        if description is not None and (description or '') != (row.description or ''):
            raise HTTPException(400, '系统角色的描述不可修改')
        name, description = None, None
    if name is not None:
        row.name = name
    if description is not None:
        row.description = description or None
    if menu_permissions is not UNSET:
        row.menu_permissions = validate_menu_permissions(menu_permissions)
    await s.commit()
    await s.refresh(row)
    return public_role(row, await user_count(s, row.code))


async def delete_role(s: AsyncSession, role_id: UUID) -> None:
    row = await get_role(s, role_id)
    if row.is_system:
        raise HTTPException(400, '系统内置角色不可删除')
    count = await user_count(s, row.code)
    if count > 0:
        raise HTTPException(400, f'仍有 {count} 个用户使用该角色，请先调整这些用户的角色')
    await s.delete(row)
    await s.commit()
    if get_settings().auth_provider == 'keycloak':
        await _sync_delete_client_role(row.code)


async def _sync_delete_client_role(code: str) -> None:
    """Keycloak 模式：删除 client role；404（已不存在）容忍。"""
    from .keycloak_admin import admin_session
    from .portal_accounts import _resource_id
    try:
        async with admin_session() as admin:
            rid = await _resource_id(admin)
            await admin.call('DELETE', f'clients/{rid}/roles/{code}')
    except HTTPException as exc:
        if exc.status_code == 404:
            return
        raise
