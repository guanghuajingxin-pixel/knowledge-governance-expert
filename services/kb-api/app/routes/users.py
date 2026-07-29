from fastapi import APIRouter, Depends
from kb_common.models import User, ApiKey
from kb_common.security import hash_password
from kb_common.config import get_settings
import secrets, hashlib
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["users"])

@router.get("/users/me")
async def me(u: User = Depends(get_current_user)):
    return {"id": str(u.id), "username": u.username, "role": u.role}

class ApiKeyIn(BaseModel):
    name: str

@router.post("/auth/api-keys")
async def create_key(body: ApiKeyIn, u: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    raw = "kb_" + secrets.token_hex(24)
    k = ApiKey(user_id=u.id, name=body.name, key_hash=hashlib.sha256(raw.encode()).hexdigest(),
               key_prefix=raw[:10])
    s.add(k); await s.commit()
    return {"id": str(k.id), "key": raw, "name": body.name}  # raw 仅此一次返回

@router.get("/auth/api-keys")
async def list_keys(u: User = Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    rows = (await s.execute(select(ApiKey).where(ApiKey.user_id == u.id))).scalars().all()
    return [{"id": str(r.id), "name": r.name, "prefix": r.key_prefix, "is_active": r.is_active} for r in rows]
