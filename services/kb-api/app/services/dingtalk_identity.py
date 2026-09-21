"""钉钉身份 → 本地用户：H5 免登 / 扫码登录 / 机器人消息归因共用的自动建档逻辑。

首次免登/扫码/首条机器人消息自动建档：users.username=dd_{dt_userid}（随机密码哈希 +
must_change_password=true，登录后可用但被强制设密）、role=viewer（仅问答可见）；
dingtalk_bindings 记录 corp/userid/unionid 与钉钉真实姓名，供展示与运营归因。
改名时仅更新绑定表姓名，username 不变。
"""
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

    base = f"dd_{dt_userid}"[:100]
    for attempt in range(2):
        # 钉钉换 userid 等场景下 dd_{userid} 可能撞已有用户名：撞了追加短后缀重试一次
        username = base if attempt == 0 else f"{base[:93]}_{secrets.token_hex(3)}"
        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(24)),
            role="viewer",
            is_active=True,
            must_change_password=True,   # 建档即强制设密：随机哈希不可登录，必须走设密页
            password_updated_at=None,
        )
        s.add(user)
        try:
            await s.flush()
            break
        except IntegrityError:
            await s.rollback()
            if attempt == 1:
                raise
    binding = DingtalkBinding(user_id=user.id, corp_id=corp_id, dt_userid=dt_userid,
                              dt_unionid=dt_unionid or None, dt_name=dt_name or None)
    s.add(binding)
    await s.commit()
    return user, binding


def user_public_dict(user: User, binding: DingtalkBinding | None = None) -> dict:
    """与 /auth/login、/users/me 同构的用户字典（前端 UserInfo）。"""
    return {
        "id": str(user.id), "username": user.username, "email": user.email or "",
        "role": user.role, "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "must_change_password": bool(user.must_change_password),
        "password_updated_at": (user.password_updated_at.isoformat()
                                if user.password_updated_at else None),
        "dingtalk_binding": {
            "dt_name": binding.dt_name or "", "dt_userid": binding.dt_userid or "",
            "dt_unionid": binding.dt_unionid or "", "corp_id": binding.corp_id or "",
            "bound_at": binding.created_at.isoformat() if binding.created_at else None,
        } if binding else None,
    }


def issue_token(user: User, binding: DingtalkBinding | None = None) -> dict:
    """与 /auth/login 同构的 JWT 响应；payload 携带 dtu/mcp 供按用户调钉钉与前端守卫。"""
    return {
        "access_token": create_jwt(
            str(user.id), user.role,
            dt_unionid=(binding.dt_unionid if binding else None),
            must_change_password=bool(user.must_change_password)),
        "token_type": "bearer",
        "user": user_public_dict(user, binding),
        "must_set_password": bool(user.must_change_password),
    }
