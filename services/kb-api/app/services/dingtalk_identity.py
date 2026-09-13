"""钉钉身份 → 本地用户：H5 免登与机器人消息归因共用的自动建档逻辑。

首次免登/首条机器人消息自动建档：users.username=dd_{dt_userid}（随机密码哈希，
不可密码登录）、role=viewer（仅问答可见）；dingtalk_bindings 记录 corp/userid/
unionid 与钉钉真实姓名，供展示与运营归因。改名时仅更新绑定表姓名，username 不变。
"""
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.models import DingtalkBinding, User
from kb_common.security import create_jwt, hash_password


async def resolve_user(s: AsyncSession, corp_id: str, dt_userid: str,
                       dt_unionid: str = "", dt_name: str = "") -> tuple[User, DingtalkBinding]:
    """按 (corp_id, dt_userid) 查绑定；不存在则自动建档。返回 (本地用户, 绑定)。"""
    row = (await s.execute(
        select(DingtalkBinding).where(DingtalkBinding.corp_id == corp_id,
                                      DingtalkBinding.dt_userid == dt_userid)
    )).scalar_one_or_none()
    if row:
        user = await s.get(User, row.user_id)
        if user and user.is_active:
            changed = False
            if dt_name and row.dt_name != dt_name:
                row.dt_name = dt_name[:100]
                changed = True
            if dt_unionid and row.dt_unionid != dt_unionid:
                row.dt_unionid = dt_unionid[:128]
                changed = True
            if changed:
                await s.commit()
            return user, row
        if user and not user.is_active:
            raise RuntimeError("对应本地用户已停用，请联系管理员")
        # 用户被删除但绑定残留：清理后重建
        await s.delete(row)
        await s.flush()

    user = User(
        username=f"dd_{dt_userid}"[:100],
        password_hash=hash_password(secrets.token_urlsafe(24)),
        role="viewer",
        is_active=True,
    )
    s.add(user)
    await s.flush()
    binding = DingtalkBinding(user_id=user.id, corp_id=corp_id, dt_userid=dt_userid,
                              dt_unionid=dt_unionid or None, dt_name=dt_name or None)
    s.add(binding)
    await s.commit()
    return user, binding


def issue_token(user: User) -> dict:
    """与 /auth/login 同构的 JWT 响应。"""
    return {
        "access_token": create_jwt(str(user.id), user.role),
        "token_type": "bearer",
        "user": {"id": str(user.id), "username": user.username, "email": user.email or "",
                 "role": user.role, "is_active": user.is_active,
                 "created_at": user.created_at.isoformat() if user.created_at else None},
    }
