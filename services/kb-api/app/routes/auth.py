"""认证接口：仅保留 local 密码登录与 OIDC 元数据下发。

账户管理已上收统一门户：设密/改密/钉钉扫码登录/账号绑定等能力均已移除，
统一登录走 GET /auth/config 下发的 OIDC 元数据（keycloak 模式）。
本地调试可经 POST /auth/dev-login 用写死令牌换发标准 JWT（仅 DEV_AUTH_TOKEN
配置时可用，生产 .env.app 禁止配置）。
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.config import get_settings
from kb_common.database import get_session
from kb_common.models import DingtalkBinding, User
from kb_common.security import verify_password
from kb_common.oidc import dev_user, oidc_config, require_local_auth
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _binding_of(s: AsyncSession, user_id) -> DingtalkBinding | None:
    return (await s.execute(
        select(DingtalkBinding).where(DingtalkBinding.user_id == user_id)
    )).scalar_one_or_none()


class LoginIn(BaseModel):
    username: str
    password: str


class DevLoginIn(BaseModel):
    token: str


@router.post("/login")
async def login(body: LoginIn, s: AsyncSession = Depends(get_session)):
    require_local_auth()
    u = (await s.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not u.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户已停用，请联系管理员")
    from app.services.dingtalk_identity import issue_token
    binding = await _binding_of(s, u.id)
    return issue_token(u, binding)


@router.post("/dev-login")
async def dev_login(body: DevLoginIn, s: AsyncSession = Depends(get_session)):
    """本地调试登录：写死令牌换发标准 JWT（与 /auth/login 同构）。

    鉴权链路完整：JWT 由本地 JWT_SECRET 签发、带过期时间，每个请求仍走
    authenticate 校验；DEV_AUTH_TOKEN 未配置时端点不存在（404）。
    """
    cfg = get_settings()
    if not cfg.dev_auth_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "本地调试登录未启用")
    try:
        matched = secrets.compare_digest(body.token, cfg.dev_auth_token)
    except TypeError:  # compare_digest 仅接受 ASCII
        matched = False
    if not matched:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "本地调试令牌不正确")
    user = await dev_user()
    from app.services.dingtalk_identity import issue_token
    binding = await _binding_of(s, user.id)
    return issue_token(user, binding)


@router.get("/config")
async def authentication_config():
    """Public metadata only; client IDs are public, no secrets are exposed."""
    return oidc_config()
