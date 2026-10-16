"""用户只读接口：账户管理已上收统一门户（Keycloak 账号中心），本服务不再提供
本地用户 CRUD / 改密 / 个人 API Key 等账户管理能力。local 模式仅保留密码登录
通道（建号走 scripts/seed_admin.py）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import User, DingtalkBinding
from app.deps import get_current_user
from app.services.dingtalk_identity import user_public_dict

router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get("/users/me")
async def me(u: User = Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """Return full UserInfo - aligns with frontend type {id,username,email,role,is_active,created_at}."""
    binding = (await s.execute(select(DingtalkBinding).where(
        DingtalkBinding.user_id == u.id))).scalar_one_or_none()
    from app.services.menu_permissions import resolve_menu_permissions
    menus = await resolve_menu_permissions(s, u)
    return user_public_dict(u, binding, menus)
