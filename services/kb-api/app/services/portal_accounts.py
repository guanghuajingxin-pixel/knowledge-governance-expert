"""统一门户账号管理：账号生命周期与角色分配。

双模式：
- local：账号存本地 PG users 表（当前服务器部署模式），密码策略本地校验；
- keycloak：账号归属 Keycloak，本地 User 行首登自动建档；全部操作经由
  platform-key-manager 服务账号调用 Keycloak Admin REST API。

角色校验统一走 portal_roles 表（4 系统角色 + 自定义角色）。
"""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.config import get_settings
from kb_common.models import PortalRole, User
from kb_common.security import hash_password

from .keycloak_admin import admin_session, configuration

logger = logging.getLogger(__name__)
ROLES = ('super_admin', 'admin', 'editor', 'viewer')


def _is_local() -> bool:
    return get_settings().auth_provider != 'keycloak'


async def validate_role(s: AsyncSession, role: str) -> None:
    """角色须为系统角色或 portal_roles 中已存在的自定义角色。"""
    if role in ROLES:
        return
    row = (await s.execute(
        select(PortalRole).where(PortalRole.code == role))).scalar_one_or_none()
    if row is None:
        raise HTTPException(400, '角色不存在')


def validate_password_policy(password: str) -> None:
    """local 模式密码策略：12 位以上，含大写、小写和数字（与 Keycloak realm 策略对齐）。"""
    if (len(password) < 12 or len(password) > 128
            or not any(c.islower() for c in password)
            or not any(c.isupper() for c in password)
            or not any(c.isdigit() for c in password)):
        raise HTTPException(400, '密码须为 12 位以上，且包含大写字母、小写字母和数字')


# ---------------------------------------------------------------- local 模式

def _local_public_user(row: User) -> dict:
    return {
        'id': str(row.id),
        'username': row.username,
        'name': '',
        'email': row.email or None,
        'enabled': bool(row.is_active),
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'roles': [row.role] if row.role else [],
    }


async def _local_get(s: AsyncSession, user_id: UUID) -> dict:
    row = await s.get(User, user_id)
    if row is None:
        raise HTTPException(404, '账号不存在')
    return _local_public_user(row)


async def _local_list(s: AsyncSession, search: str, first: int, max_results: int) -> list[dict]:
    q = select(User).order_by(User.created_at, User.username)
    if search:
        like = f'%{search}%'
        q = q.where(or_(User.username.ilike(like), User.email.ilike(like)))
    rows = (await s.execute(q.offset(first).limit(max_results))).scalars().all()
    return [_local_public_user(r) for r in rows]


async def _local_create(s: AsyncSession, *, username: str, email: str | None, role: str,
                        password: str, temporary: bool) -> dict:
    await validate_role(s, role)
    validate_password_policy(password)
    exists = (await s.execute(select(User).where(
        User.username == username))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, '用户名已存在，请更换后重试')
    row = User(username=username, password_hash=hash_password(password),
               email=email, role=role, must_change_password=temporary)
    s.add(row)
    await s.commit()
    return _local_public_user(row)


async def _local_update(s: AsyncSession, user_id: UUID, *, email=None, role=None,
                        enabled=None) -> dict:
    row = await s.get(User, user_id)
    if row is None:
        raise HTTPException(404, '账号不存在')
    if email is not None:
        row.email = email or None
    if role is not None:
        await validate_role(s, role)
        row.role = role
    if enabled is not None:
        row.is_active = enabled
    await s.commit()
    return _local_public_user(row)


async def _local_reset_password(s: AsyncSession, user_id: UUID, *, password: str,
                                temporary: bool) -> None:
    row = await s.get(User, user_id)
    if row is None:
        raise HTTPException(404, '账号不存在')
    validate_password_policy(password)
    row.password_hash = hash_password(password)
    row.must_change_password = temporary
    await s.commit()


async def _local_delete(s: AsyncSession, user_id: UUID) -> None:
    row = await s.get(User, user_id)
    if row is None:
        raise HTTPException(404, '账号不存在')
    await s.delete(row)
    await s.commit()


# ---------------------------------------------------------------- keycloak 模式

def public_user(row, roles=()):
    created = row.get('createdTimestamp')
    return {
        'id': row['id'],
        'username': row.get('username') or '',
        'name': row.get('firstName') or '',
        'email': row.get('email') or None,
        'enabled': bool(row.get('enabled')),
        'created_at': (datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
                       if isinstance(created, (int, float)) else None),
        'roles': sorted(roles),
    }


async def _resource_id(admin):
    """知识治理资源客户端（kb-api）UUID——角色挂载点。"""
    cfg = configuration()
    rows = await admin.call('GET', 'clients', params={'clientId': cfg.oidc_audience, 'exact': 'true'})
    if len(rows) != 1:
        raise HTTPException(503, '未找到知识治理资源客户端，请检查身份中心配置')
    return rows[0]['id']


async def _with_roles(admin, row):
    resource_id = await _resource_id(admin)
    mappings = await admin.call('GET', f"users/{row['id']}/role-mappings/clients/{resource_id}")
    return public_user(row, [m['name'] for m in mappings])


async def _kc_get(user_id: UUID) -> dict:
    async with admin_session() as admin:
        row = await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        return await _with_roles(admin, row)


async def _kc_list(search: str, first: int, max_results: int) -> list[dict]:
    async with admin_session() as admin:
        params = {'first': first, 'max': max_results}
        if search:
            params['search'] = search
        # 管理端点会混入服务账号（platform-key-manager 等），对管理员不可见也不可改
        rows = [row for row in await admin.call('GET', 'users', params=params)
                if not row.get('serviceAccountClientLink')]
        if not rows:
            return []
        resource_id = await _resource_id(admin)
        # Keycloak 无批量角色端点：按页并发补齐各账号的知识治理角色
        mappings = await asyncio.gather(*[
            admin.call('GET', f"users/{row['id']}/role-mappings/clients/{resource_id}")
            for row in rows])
        return [public_user(row, [m['name'] for m in mapping])
                for row, mapping in zip(rows, mappings)]


async def _kc_create(s: AsyncSession, *, username: str, name: str, email: str | None, role: str,
                     password: str, temporary: bool) -> dict:
    await validate_role(s, role)
    async with admin_session() as admin:
        resource_id = await _resource_id(admin)
        role_row = await admin.call('GET', f'clients/{resource_id}/roles/{role}',
                                    not_found='角色不存在，请检查身份中心配置')
        payload = {'username': username, 'firstName': name, 'enabled': True}
        if email:
            payload['email'] = email
            # realm 开启了 verifyEmail：不置已验证标记，首登会被 VERIFY_EMAIL 动作卡住
            payload['emailVerified'] = True
        user_id = None
        try:
            await admin.call('POST', 'users', json=payload, conflict='用户名已存在，请更换后重试')
            rows = await admin.call('GET', 'users', params={'username': username, 'exact': 'true'})
            if not rows:
                raise HTTPException(502, '账号已创建但无法定位，请到账号列表检查')
            user_id = rows[0]['id']
            await admin.call('PUT', f'users/{user_id}/reset-password',
                             json={'type': 'password', 'value': password, 'temporary': temporary})
            await admin.call('POST', f'users/{user_id}/role-mappings/clients/{resource_id}', json=[role_row])
        except Exception:
            # 与平台密钥签发相同的补偿策略：失败即回收半成品账号
            if user_id:
                try:
                    await admin.call('DELETE', f'users/{user_id}')
                except Exception:
                    logger.error('清理未完成创建的统一账号失败 username=%s', username)
            raise
        return public_user({**payload, 'id': user_id}, [role])


async def _kc_update(s: AsyncSession, user_id: UUID, *, name=None, email=None, role=None,
                     enabled=None) -> dict:
    async with admin_session() as admin:
        row = await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        changes = {}
        if name is not None:
            changes['firstName'] = name
        if email is not None:
            # 空串表示清除邮箱；重置 emailVerified 避免残留“已验证”状态
            changes['email'] = email or None
            changes['emailVerified'] = bool(email)
        if enabled is not None:
            changes['enabled'] = enabled
        if changes:
            await admin.call('PUT', f'users/{user_id}', json=changes)
        if role is None:
            return await _with_roles(admin, {**row, **changes})
        await validate_role(s, role)
        resource_id = await _resource_id(admin)
        current = await admin.call('GET', f'users/{user_id}/role-mappings/clients/{resource_id}')
        if role not in [m['name'] for m in current]:
            role_row = await admin.call('GET', f'clients/{resource_id}/roles/{role}',
                                        not_found='角色不存在，请检查身份中心配置')
            await admin.call('POST', f'users/{user_id}/role-mappings/clients/{resource_id}', json=[role_row])
        stale = [m for m in current if m['name'] != role]
        if stale:
            await admin.call('DELETE', f'users/{user_id}/role-mappings/clients/{resource_id}', json=stale)
        return public_user({**row, **changes}, [role])


async def _kc_reset_password(user_id: UUID, *, password: str, temporary: bool) -> None:
    async with admin_session() as admin:
        await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        await admin.call('PUT', f'users/{user_id}/reset-password',
                         json={'type': 'password', 'value': password, 'temporary': temporary})


async def _kc_delete(user_id: UUID) -> None:
    async with admin_session() as admin:
        await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        await admin.call('DELETE', f'users/{user_id}')


# ---------------------------------------------------------------- 对外统一入口

async def get_account(s: AsyncSession, user_id: UUID) -> dict:
    if _is_local():
        return await _local_get(s, user_id)
    return await _kc_get(user_id)


async def list_accounts(s: AsyncSession, search: str = '', first: int = 0,
                        max_results: int = 21) -> list[dict]:
    if _is_local():
        return await _local_list(s, search, first, max_results)
    return await _kc_list(search, first, max_results)


async def create_account(s: AsyncSession, *, username: str, name: str, email: str | None,
                         role: str, password: str, temporary: bool) -> dict:
    if _is_local():
        return await _local_create(s, username=username, email=email, role=role,
                                   password=password, temporary=temporary)
    return await _kc_create(s, username=username, name=name, email=email, role=role,
                            password=password, temporary=temporary)


async def update_account(s: AsyncSession, user_id: UUID, *, name=None, email=None, role=None,
                         enabled=None) -> dict:
    if _is_local():
        # local 模式无姓名列（name 仅 Keycloak 有 firstName）
        return await _local_update(s, user_id, email=email, role=role, enabled=enabled)
    return await _kc_update(s, user_id, name=name, email=email, role=role, enabled=enabled)


async def reset_password(s: AsyncSession, user_id: UUID, *, password: str,
                         temporary: bool) -> None:
    if _is_local():
        await _local_reset_password(s, user_id, password=password, temporary=temporary)
    else:
        await _kc_reset_password(user_id, password=password, temporary=temporary)


async def delete_account(s: AsyncSession, user_id: UUID) -> None:
    if _is_local():
        await _local_delete(s, user_id)
    else:
        await _kc_delete(user_id)
