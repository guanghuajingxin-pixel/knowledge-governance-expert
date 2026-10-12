"""统一门户账号管理：账号与角色都归属 Keycloak，本地 User 行首登自动建档。

全部操作经由 platform-key-manager 服务账号调用 Keycloak Admin REST API；
用户名唯一性、密码策略（12 位 + 大小写 + 数字）等约束由 Keycloak 兜底校验。
"""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from .keycloak_admin import admin_session, configuration

logger = logging.getLogger(__name__)
ROLES = ('super_admin', 'admin', 'editor', 'viewer')


def validate_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(400, '角色无效')


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


async def get_account(user_id: UUID):
    async with admin_session() as admin:
        row = await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        return await _with_roles(admin, row)


async def list_accounts(search: str = '', first: int = 0, max_results: int = 21):
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


async def create_account(*, username: str, name: str, email: str | None, role: str,
                         password: str, temporary: bool):
    validate_role(role)
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


async def update_account(user_id: UUID, *, name=None, email=None, role=None, enabled=None):
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
        validate_role(role)
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


async def reset_password(user_id: UUID, *, password: str, temporary: bool):
    async with admin_session() as admin:
        await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        await admin.call('PUT', f'users/{user_id}/reset-password',
                         json={'type': 'password', 'value': password, 'temporary': temporary})


async def delete_account(user_id: UUID):
    async with admin_session() as admin:
        await admin.call('GET', f'users/{user_id}', not_found='账号不存在')
        await admin.call('DELETE', f'users/{user_id}')
