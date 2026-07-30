from fastapi import APIRouter, Depends, HTTPException, status
from kb_common.models import User, ApiKey
from kb_common.security import hash_password
from kb_common.config import get_settings
import secrets, hashlib, uuid
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["users"])


def _user_dict(u: User) -> dict:
    return {"id": str(u.id), "username": u.username, "email": u.email or "",
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None}


@router.get("/users/me")
async def me(u: User = Depends(get_current_user)):
    """Return full UserInfo - aligns with frontend type {id,username,email,role,is_active,created_at}."""
    return _user_dict(u)


class UserCreate(BaseModel):
    username: str
    password: str
    email: str | None = None
    role: str = "viewer"   # 校验在 handler


class UserUpdate(BaseModel):
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None   # 非空则重置


VALID_ROLES = {"super_admin", "admin", "editor", "viewer"}


@router.get("/users")
async def list_users(u: User = Depends(require_role("super_admin", "admin")),
                     s: AsyncSession = Depends(get_session), page: int = 1, size: int = 20):
    page = max(1, page); size = max(1, min(100, size))
    total = (await s.execute(select(func.count(User.id)))).scalar_one()
    rows = (await s.execute(select(User).order_by(User.created_at.desc())
                            .offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [_user_dict(r) for r in rows], "total": total, "page": page, "size": size}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, u: User = Depends(require_role("super_admin", "admin")),
                      s: AsyncSession = Depends(get_session)):
    if body.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法角色: {body.role}")
    if (await s.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    nu = User(username=body.username, password_hash=hash_password(body.password),
              email=body.email, role=body.role)
    s.add(nu); await s.commit(); await s.refresh(nu)
    return _user_dict(nu)


@router.put("/users/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdate,
                      u: User = Depends(require_role("super_admin", "admin")),
                      s: AsyncSession = Depends(get_session)):
    tu = await s.get(User, user_id)
    if not tu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    # 不允许把最后一个 super_admin 降级或禁用
    if tu.role == "super_admin" and ((body.role is not None and body.role != "super_admin")
                                     or (body.is_active is False)):
        cnt = (await s.execute(select(func.count(User.id))
                .where(User.role == "super_admin", User.is_active == True))).scalar_one()
        if cnt <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少保留一个启用的超级管理员")
    if body.email is not None: tu.email = body.email
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"非法角色: {body.role}")
        tu.role = body.role
    if body.is_active is not None: tu.is_active = body.is_active
    if body.password: tu.password_hash = hash_password(body.password)
    await s.commit(); await s.refresh(tu)
    return _user_dict(tu)


@router.delete("/users/{user_id}")
async def delete_user(user_id: uuid.UUID, u: User = Depends(require_role("super_admin", "admin")),
                      s: AsyncSession = Depends(get_session)):
    if user_id == u.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    tu = await s.get(User, user_id)
    if not tu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if tu.role == "super_admin":
        cnt = (await s.execute(select(func.count(User.id))
                .where(User.role == "super_admin", User.is_active == True))).scalar_one()
        if cnt <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少保留一个超级管理员")
    await s.delete(tu); await s.commit()
    return {"ok": True}

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
