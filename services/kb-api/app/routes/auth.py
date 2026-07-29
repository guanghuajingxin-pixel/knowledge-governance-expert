from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import User
from kb_common.security import verify_password, create_jwt
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class LoginIn(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(body: LoginIn, s: AsyncSession = Depends(get_session)):
    u = (await s.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    # user object aligns with frontend UserInfo (D4 fix - include email/is_active/created_at)
    return {"access_token": create_jwt(str(u.id), u.role),
            "token_type": "bearer",
            "user": {"id": str(u.id), "username": u.username, "email": u.email or "",
                     "role": u.role, "is_active": u.is_active,
                     "created_at": u.created_at.isoformat() if u.created_at else None}}
