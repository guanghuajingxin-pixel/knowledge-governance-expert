from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.security import decode_jwt
from kb_common.models import User

bearer = HTTPBearer()

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

def require_role(*roles):
    async def checker(u: User = Depends(get_current_user)) -> User:
        if u.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return u
    return checker
