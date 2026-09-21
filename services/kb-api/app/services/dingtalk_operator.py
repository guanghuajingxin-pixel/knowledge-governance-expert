"""钉钉操作人身份解析：把「全局单值 operator」升级为「按登录用户 / 按同步源 owner」。

两条链路：
1. 交互链路（知识中心浏览、Agent 工具，async Session）：user_union_id() 取当前登录
   用户的绑定 unionId；未绑定返回 None，调用方回退全局服务账号。
2. 后台同步链路（sync engine，同步 Session）：resolve_source_operator_sync() 按
   sync_sources.owner_user_id → 绑定 unionId；owner 缺失/未绑定回退全局
   dingtalk_operator_union_id，并返回来源标记（owner_binding | global_fallback）
   写入 sync_runs.operator_source 留痕。

均带 60s TTL 进程内缓存：同步一个源要调成百上千次钉钉接口，不能每次都查 DB。
绑定创建/解绑、同步源 owner 变更时调 invalidate_* 主动失效。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

_TTL = 60.0
# user_id(str) -> (union_id|None, expire_at)
_user_cache: dict[str, tuple[str | None, float]] = {}
# source_id(int) -> (union_id, source_tag, expire_at)
_source_cache: dict[int, tuple[str, str, float]] = {}

OWNER_BINDING = "owner_binding"
GLOBAL_FALLBACK = "global_fallback"


class OperatorUnavailable(RuntimeError):
    """同步源既没有可用 owner 绑定，也没配全局服务账号——同步必须失败并提示配置。"""


def invalidate_user(user_id) -> None:
    _user_cache.pop(str(user_id), None)


def invalidate_source(source_id: int | None = None) -> None:
    if source_id is None:
        _source_cache.clear()
    else:
        _source_cache.pop(source_id, None)


def invalidate_all() -> None:
    _user_cache.clear()
    _source_cache.clear()


# ===================== 用户维度（交互链路） =====================
def user_union_id_cached(user_id) -> str | None:
    hit = _user_cache.get(str(user_id))
    if hit and hit[1] > time.monotonic():
        return hit[0]
    return None


def _put_user(user_id, union: str | None) -> None:
    _user_cache[str(user_id)] = (union, time.monotonic() + _TTL)


async def user_union_id(db, user_id) -> str | None:
    """async Session 版本：本地用户的钉钉 unionId（未绑定返回 None）。"""
    cached = user_union_id_cached(user_id)
    if cached is not None:
        return cached
    from kb_common.models import DingtalkBinding
    row = (await db.execute(
        select(DingtalkBinding).where(DingtalkBinding.user_id == user_id)
    )).scalar_one_or_none()
    union = (row.dt_unionid or None) if row else None
    _put_user(user_id, union)
    return union


def user_union_id_sync(db, user_id) -> str | None:
    """同步 Session 版本（后台任务/线程池内使用）。"""
    cached = user_union_id_cached(user_id)
    if cached is not None:
        return cached
    from kb_common.models import DingtalkBinding
    row = db.execute(
        select(DingtalkBinding).where(DingtalkBinding.user_id == user_id)
    ).scalar_one_or_none()
    union = (row.dt_unionid or None) if row else None
    _put_user(user_id, union)
    return union


async def _global_operator(db) -> str:
    from kb_common.models import Setting
    row = (await db.execute(
        select(Setting).where(Setting.key == "dingtalk_operator_union_id")
    )).scalar_one_or_none()
    return (row.value or "").strip() if row else ""


def _global_operator_sync(db) -> str:
    from kb_common.models import Setting
    row = db.execute(
        select(Setting).where(Setting.key == "dingtalk_operator_union_id")
    ).scalar_one_or_none()
    return (row.value or "").strip() if row else ""


# ===================== 同步源维度（后台链路） =====================
def resolve_source_operator_sync(db, source) -> tuple[str, str]:
    """同步源操作人身份（同步 Session）：返回 (union_id, source_tag)。

    source 为 SyncSource 对象（或带 id/owner_user_id 属性的对象）。
    owner 绑定与全局兜底皆无时抛 OperatorUnavailable。
    """
    sid = int(getattr(source, "id", 0) or 0)
    hit = _source_cache.get(sid)
    if hit and hit[2] > time.monotonic():
        return hit[0], hit[1]

    owner_id = getattr(source, "owner_user_id", None)
    union: str | None = None
    tag = GLOBAL_FALLBACK
    if owner_id:
        union = user_union_id_sync(db, owner_id)
        if union:
            tag = OWNER_BINDING
    if not union:
        union = _global_operator_sync(db) or None
        tag = GLOBAL_FALLBACK
    if not union:
        raise OperatorUnavailable(
            f"同步源 {sid} 无法确定钉钉操作人：owner 未绑定钉钉且系统配置缺少 "
            f"dingtalk_operator_union_id（服务账号兜底）")
    _source_cache[sid] = (union, tag, time.monotonic() + _TTL)
    return union, tag


async def resolve_source_operator(db, source) -> tuple[str, str]:
    """async Session 版本，语义同 resolve_source_operator_sync。"""
    sid = int(getattr(source, "id", 0) or 0)
    hit = _source_cache.get(sid)
    if hit and hit[2] > time.monotonic():
        return hit[0], hit[1]

    owner_id = getattr(source, "owner_user_id", None)
    union: str | None = None
    tag = GLOBAL_FALLBACK
    if owner_id:
        union = await user_union_id(db, owner_id)
        if union:
            tag = OWNER_BINDING
    if not union:
        union = await _global_operator(db) or None
        tag = GLOBAL_FALLBACK
    if not union:
        raise OperatorUnavailable(
            f"同步源 {sid} 无法确定钉钉操作人：owner 未绑定钉钉且系统配置缺少 "
            f"dingtalk_operator_union_id（服务账号兜底）")
    _source_cache[sid] = (union, tag, time.monotonic() + _TTL)
    return union, tag


async def effective_operator(db, user_id=None) -> tuple[str | None, str]:
    """交互链路统一入口：优先登录用户绑定，回退全局。返回 (union_id|None, tag)。"""
    if user_id is not None:
        union = await user_union_id(db, user_id)
        if union:
            return union, OWNER_BINDING
    glob = await _global_operator(db)
    return (glob or None), GLOBAL_FALLBACK


def source_owner_for_display(source: Any) -> str:
    """同步源列表页展示 owner 用户名用（路由层自行 join users）。"""
    return str(getattr(source, "owner_user_id", "") or "")
