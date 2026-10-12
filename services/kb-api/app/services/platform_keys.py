"""Keycloak owns platform application credentials; this service stores no secrets."""
from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

from fastapi import HTTPException

from .keycloak_admin import admin_session, configuration

MARKER = 'knowledge-platform-api'
PREFIX = 'platform-api-'
logger = logging.getLogger(__name__)


def managed(row):
    return (row.get('clientId', '').startswith(PREFIX)
            and row.get('attributes', {}).get('platform.api.managed') == MARKER)


def public(row):
    attrs = row.get('attributes') or {}
    return {'id': row['id'], 'client_id': row['clientId'], 'name': row.get('name') or row['clientId'],
            'enabled': bool(row.get('enabled')), 'created_at': attrs.get('platform.api.created_at'),
            'permissions': ['knowledge:retrieve']}


async def get_managed(admin, key_id: UUID):
    row = await admin.call('GET', f'clients/{key_id}')
    if not managed(row):
        raise HTTPException(404, '未找到平台 API Key')
    return row


async def list_keys():
    async with admin_session() as admin:
        rows, offset = [], 0
        while True:
            batch = await admin.call('GET', 'clients', params={
                'clientId': PREFIX, 'search': 'true', 'first': offset, 'max': 100,
            })
            rows.extend(public(row) for row in batch if managed(row))
            if len(batch) < 100:
                break
            offset += 100
    return sorted(rows, key=lambda row: row['created_at'] or '', reverse=True)


async def create_key(name: str, actor_id: str):
    cfg = configuration()
    async with admin_session() as admin:
        resources = await admin.call('GET', 'clients', params={'clientId': cfg.oidc_audience, 'exact': 'true'})
        if len(resources) != 1:
            raise HTTPException(503, '未找到知识治理资源客户端，请检查身份中心配置')
        resource_id = resources[0]['id']
        role = await admin.call('GET', f'clients/{resource_id}/roles/knowledge:retrieve')
        client_id = PREFIX + uuid4().hex
        payload = {
            'clientId': client_id, 'name': name, 'protocol': 'openid-connect',
            'enabled': False, 'publicClient': False, 'clientAuthenticatorType': 'client-secret',
            'serviceAccountsEnabled': True, 'standardFlowEnabled': False,
            'implicitFlowEnabled': False, 'directAccessGrantsEnabled': False,
            'fullScopeAllowed': False, 'defaultClientScopes': ['roles'],
            'attributes': {'platform.api.managed': MARKER,
                           'platform.api.created_at': datetime.now(timezone.utc).isoformat(),
                           'platform.api.created_by': actor_id},
            'protocolMappers': [
                {'name': 'platform-resource-audience', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-audience-mapper', 'config': {
                     'included.client.audience': cfg.oidc_audience, 'access.token.claim': 'true', 'id.token.claim': 'false'}},
                {'name': 'platform-api-marker', 'protocol': 'openid-connect',
                 'protocolMapper': 'oidc-hardcoded-claim-mapper', 'config': {
                     'claim.name': 'platform_api', 'claim.value': 'true', 'jsonType.label': 'boolean',
                     'access.token.claim': 'true', 'id.token.claim': 'false'}},
            ],
        }
        key_id = None
        try:
            await admin.call('POST', 'clients', json=payload)
            rows = await admin.call('GET', 'clients', params={'clientId': client_id, 'exact': 'true'})
            key_id = rows[0]['id']
            service_user = await admin.call('GET', f'clients/{key_id}/service-account-user')
            await admin.call('POST', f'users/{service_user["id"]}/role-mappings/clients/{resource_id}', json=[role])
            await admin.call('POST', f'clients/{key_id}/scope-mappings/clients/{resource_id}', json=[role])
            secret = (await admin.call('GET', f'clients/{key_id}/client-secret'))['value']
            await admin.call('PUT', f'clients/{key_id}', json={'enabled': True})
            return {**public({**payload, 'id': key_id, 'enabled': True}), 'raw_key': f'{client_id}:{secret}'}
        except Exception:
            # Created disabled; a timeout before resolving its ID cannot expose a usable key.
            if key_id:
                try:
                    await admin.call('DELETE', f'clients/{key_id}')
                except Exception:
                    logger.error('清理未完成签发的平台应用失败 client_id=%s', client_id)
            raise


async def reveal_key(key_id: UUID):
    """回显完整密钥 client_id:secret（Keycloak 保存明文 secret，可随时读取）。"""
    async with admin_session() as admin:
        row = await get_managed(admin, key_id)
        secret = (await admin.call('GET', f'clients/{key_id}/client-secret'))['value']
        return {'client_id': row['clientId'], 'raw_key': f"{row['clientId']}:{secret}"}


async def update_key(key_id: UUID, *, name=None, enabled=None):
    async with admin_session() as admin:
        row = await get_managed(admin, key_id)
        changes = {}
        if name is not None:
            changes['name'] = name
        if enabled is not None:
            changes['enabled'] = enabled
        await admin.call('PUT', f'clients/{key_id}', json=changes)
        return public({**row, **changes})


async def delete_key(key_id: UUID):
    async with admin_session() as admin:
        await get_managed(admin, key_id)
        await admin.call('DELETE', f'clients/{key_id}')
