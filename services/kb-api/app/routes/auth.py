"""认证接口：仅保留 local 密码登录与 OIDC 元数据下发。

账户管理已上收统一门户：设密/改密/钉钉扫码登录/账号绑定等能力均已移除，
统一登录走 GET /auth/config 下发的 OIDC 元数据（keycloak 模式）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import DingtalkBinding, User
from kb_common.security import verify_password
from kb_common.oidc import oidc_config, require_local_auth
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _binding_of(s: AsyncSession, user_id) -> DingtalkBinding | None:
    return (await s.execute(
        select(DingtalkBinding).where(DingtalkBinding.user_id == user_id)
    )).scalar_one_or_none()


class LoginIn(BaseModel):
    username: str
    password: str


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


@router.get("/config")
async def authentication_config():
    """Public metadata only; client IDs are public, no secrets are exposed."""
    return oidc_config()
