"""共享 Keycloak Admin REST 客户端。

账号与应用凭据都归属 Keycloak，kb-api 不落任何密钥。平台 API Key 管理与
统一门户账号管理均经由 platform-key-manager 服务账号（由
deploy/keycloak/build/provision-platform-keys.sh 建立）调用管理 API。
"""
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import HTTPException

from kb_common.config import get_settings
from kb_common.oidc import enabled, oidc_config

logger = logging.getLogger(__name__)


def configuration():
    cfg = get_settings()
    if not enabled():
        raise HTTPException(503, '请先启用 Keycloak 统一认证后再执行此操作')
    oidc_config()
    if not cfg.oidc_admin_client_id or not cfg.oidc_admin_client_secret.get_secret_value():
        raise HTTPException(503, '未配置身份中心管理服务账号，请按 API 调用说明完成身份中心接入')
    return cfg


def _keycloak_error(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ''
    if isinstance(body, dict):
        return str(body.get('errorMessage') or body.get('error_description') or '')
    return ''


class KeycloakAdmin:
    def __init__(self, client, base):
        self.client, self.base = client, base

    async def call(self, method, path, *, not_found=None, conflict=None, **kwargs):
        """调用管理 API。not_found / conflict 覆盖默认错误文案（按业务域给提示）。"""
        try:
            response = await self.client.request(method, f'{self.base}/{path}', **kwargs)
            if response.status_code == 404:
                raise HTTPException(404, not_found or '平台应用或检索角色不存在，请检查身份中心配置')
            if response.status_code in (401, 403):
                raise HTTPException(503, '管理服务账号权限不足，请检查身份中心授权')
            if response.status_code == 409:
                raise HTTPException(409, conflict or '应用已存在，请刷新列表')
            if response.status_code == 400:
                # 密码策略不满足等场景：透传 Keycloak 的具体原因
                raise HTTPException(400, _keycloak_error(response) or '身份中心拒绝了该请求，请检查输入')
            response.raise_for_status()
            return response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, '身份中心暂不可用，请稍后重试') from exc


@asynccontextmanager
async def admin_session():
    cfg = configuration()
    issuer = cfg.oidc_issuer.rstrip('/')
    root, realm = issuer.rsplit('/realms/', 1)
    base = cfg.oidc_admin_url.rstrip('/') or f'{root}/admin/realms/{realm}'
    token_url = cfg.oidc_token_url or f'{issuer}/protocol/openid-connect/token'
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        try:
            response = await client.post(token_url, data={
                'grant_type': 'client_credentials', 'client_id': cfg.oidc_admin_client_id,
                'client_secret': cfg.oidc_admin_client_secret.get_secret_value(),
            })
            response.raise_for_status()
            token = response.json()['access_token']
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(503, '身份中心管理服务账号无法认证，请检查身份中心配置') from exc
        client.headers['Authorization'] = f'Bearer {token}'
        yield KeycloakAdmin(client, base)
