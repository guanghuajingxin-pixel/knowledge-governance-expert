"""菜单权限解析：用户级覆盖 > 角色配置；super_admin 硬编码旁路。

语义（精确优先级）：
1. user.role == 'super_admin' → None（全部菜单）
2. portal_user_menu_overrides 有行 → 该行列表（删行 = 恢复跟随角色）
3. portal_roles（by code）行 menu_permissions 非 NULL → 该列表；NULL → None（全部）
4. 兜底（角色行缺失/漂移）→ None

菜单可见性 fail-open：它不是安全边界，真正的边界是 require_role——
自定义角色用户对受管端点只有 viewer 级权限。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.models import PortalRole, PortalUserMenuOverride, User


async def resolve_menu_permissions(s: AsyncSession, user: User) -> list[str] | None:
    if user.role == "super_admin":
        return None
    override = (await s.execute(
        select(PortalUserMenuOverride).where(
            PortalUserMenuOverride.user_id == str(user.id)))).scalar_one_or_none()
    if override is not None:
        return list(override.menu_permissions or [])
    return await _role_menu_permissions(s, user.role)


async def _role_menu_permissions(s: AsyncSession, role_code: str) -> list[str] | None:
    row = (await s.execute(
        select(PortalRole).where(PortalRole.code == role_code))).scalar_one_or_none()
    if row is None or row.menu_permissions is None:
        return None
    return list(row.menu_permissions)


async def role_menu_override(s: AsyncSession, user_id: str) -> list[str] | None:
    """用户级覆盖原始值：无行 → None（跟随角色）。"""
    row = (await s.execute(
        select(PortalUserMenuOverride).where(
            PortalUserMenuOverride.user_id == user_id))).scalar_one_or_none()
    if row is None:
        return None
    return list(row.menu_permissions or [])


async def set_role_menu_override(s: AsyncSession, user_id: str,
                                menu_permissions: list[str] | None) -> None:
    """menu_permissions=None 删除覆盖行（恢复跟随角色）；否则 upsert。"""
    row = (await s.execute(
        select(PortalUserMenuOverride).where(
            PortalUserMenuOverride.user_id == user_id))).scalar_one_or_none()
    if menu_permissions is None:
        if row is not None:
            await s.delete(row)
            await s.commit()
        return
    if row is None:
        s.add(PortalUserMenuOverride(user_id=user_id,
                                     menu_permissions=menu_permissions))
    else:
        row.menu_permissions = menu_permissions
    await s.commit()


async def known_role_codes(s: AsyncSession) -> set[str]:
    """全部可分配角色 code（供 oidc 自定义角色登录校验）。"""
    rows = (await s.execute(select(PortalRole.code))).scalars().all()
    return set(rows)


async def overrides_for(s: AsyncSession, user_ids: list[str]) -> dict[str, list[str]]:
    """批量查询用户级覆盖原始值（无行 → 不在返回字典中 = 跟随角色）。"""
    if not user_ids:
        return {}
    rows = (await s.execute(
        select(PortalUserMenuOverride).where(
            PortalUserMenuOverride.user_id.in_(user_ids)))).scalars().all()
    return {row.user_id: list(row.menu_permissions or []) for row in rows}


async def resolve_for_account(s: AsyncSession, account: dict) -> list[str] | None:
    """按账号字典（id/roles）解析生效菜单权限——Keycloak 用户无本地行也能解析。"""
    if 'super_admin' in account.get('roles', []):
        return None
    override = await role_menu_override(s, str(account['id']))
    if override is not None:
        return override
    for role in account.get('roles', []):
        perms = await _role_menu_permissions(s, role)
        if perms is not None:
            return perms
    return None
