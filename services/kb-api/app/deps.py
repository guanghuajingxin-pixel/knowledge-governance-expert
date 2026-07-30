from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.security import decode_jwt
from kb_common.models import User, ApiKey
import hashlib
from datetime import datetime, timezone

bearer = HTTPBearer(auto_error=False)

# get_current_user 保持不变（仅 JWT，管理类接口用）--保留原实现。
async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                           s: AsyncSession = Depends(get_session)) -> User:
    try:
        payload = decode_jwt(cred.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效凭证")
    user = await s.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    return user

async def get_principal(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    s: AsyncSession = Depends(get_session),
) -> User:
    """JWT 或 API Key 双通道鉴权（检索/问答等程序化读访问用）。
    先试 JWT；若 Bearer token 不是有效 JWT，再按 API Key 查。"""
    # 1) 试 JWT
    if cred and cred.credentials:
        try:
            payload = decode_jwt(cred.credentials)
            user = await s.get(User, payload["sub"])
            if user and user.is_active:
                return user
        except Exception:
            pass  # 不是 JWT，落到 API Key 路径
    # 2) 试 API Key：Bearer token 或 X-API-Key 头都可能是 raw key
    raw = x_api_key or (cred.credentials if cred else None)
    if raw:
        h = hashlib.sha256(raw.encode()).hexdigest()
        k = (await s.execute(
            select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active == True)
        )).scalar_one_or_none()
        if k:
            user = await s.get(User, k.user_id)
            if user and user.is_active:
                k.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await s.commit()
                return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效凭证")

def require_role(*roles):
    async def checker(u: User = Depends(get_current_user)) -> User:
        if u.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return u
    return checker
