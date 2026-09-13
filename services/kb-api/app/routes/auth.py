from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Setting, User
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


class DingtalkLoginIn(BaseModel):
    auth_code: str


@router.get("/dingtalk-config")
async def dingtalk_config(s: AsyncSession = Depends(get_session)):
    """公开端点：H5 免登前置（corpId + 开关）。未配置 corpId 时前端回退账号登录。"""
    row = (await s.execute(select(Setting).where(Setting.key == "dingtalk_corp_id"))).scalar_one_or_none()
    corp = (row.value if row else "") or ""
    return {"corp_id": corp.strip(), "auto_login_enabled": bool(corp.strip())}


@router.post("/dingtalk-login")
async def dingtalk_login(body: DingtalkLoginIn, s: AsyncSession = Depends(get_session)):
    """钉钉 H5 免登：authCode → 员工身份 → 本地用户（首次自动建档）→ JWT。"""
    from kb_common.clients import dingtalk_client
    from app.services.dingtalk_identity import issue_token, resolve_user

    row = (await s.execute(select(Setting).where(Setting.key == "dingtalk_corp_id"))).scalar_one_or_none()
    corp_id = ((row.value if row else "") or "").strip()
    if not corp_id:
        raise HTTPException(400, "钉钉免登未启用：请先在系统配置中填写 corpId")
    # 配置页保存的凭证即时生效（不依赖重启加载 env）
    await dingtalk_client.sync_runtime_config()
    try:
        info = await dingtalk_client.get_user_info_by_code(body.auth_code.strip())
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    try:
        user, _binding = await resolve_user(s, corp_id, info["userid"],
                                            info.get("unionid", ""), info.get("name", ""))
    except RuntimeError as e:
        raise HTTPException(403, str(e))
    out = issue_token(user)
    out["user"]["display_name"] = info.get("name") or user.username
    return out
