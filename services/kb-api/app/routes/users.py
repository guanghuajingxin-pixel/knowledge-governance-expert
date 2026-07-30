from fastapi import APIRouter, Depends, HTTPException, status
from kb_common.models import User, ApiKey
from kb_common.security import hash_password
from kb_common.config import get_settings
import secrets, hashlib, uuid
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["users"])

@router.get("/users/me")
async def me(u: User = Depends(get_current_user)):
    """Return full UserInfo - aligns with frontend type {id,username,email,role,is_active,created_at}."""
    return {"id": str(u.id), "username": u.username, "email": u.email or "",
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None}

class ApiKeyIn(BaseModel):
    name: str

@router.post("/auth/api-keys")
async def create_key(body: ApiKeyIn, u: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    raw = "kb_" + secrets.token_hex(24)
    k = ApiKey(user_id=u.id, name=body.name, key_hash=hashlib.sha256(raw.encode()).hexdigest(),
               key_prefix=raw[:10])
    s.add(k); await s.commit(); await s.refresh(k)
    # raw_key 仅此一次返回 - aligns with frontend ApiKeyCreated.raw_key
    return {"id": str(k.id), "name": k.name, "key_prefix": k.key_prefix,
            "raw_key": raw, "is_active": k.is_active,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None}

@router.get("/auth/api-keys")
async def list_keys(u: User = Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    rows = (await s.execute(select(ApiKey).where(ApiKey.user_id == u.id)
                            .order_by(ApiKey.created_at.desc()))).scalars().all()
    # key_prefix (not prefix) - aligns with frontend ApiKey type
    return [{"id": str(r.id), "name": r.name, "key_prefix": r.key_prefix,
             "is_active": r.is_active,
             "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

@router.delete("/auth/api-keys/{key_id}")
async def delete_key(key_id: uuid.UUID, u: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    k = await s.get(ApiKey, key_id)
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key 不存在")
    if k.user_id != u.id and u.role not in ("super_admin", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权删除他人 Key")
    await s.delete(k); await s.commit()
    return {"ok": True}
