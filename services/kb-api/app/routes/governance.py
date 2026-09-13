"""知识治理路由：治理标准（钉钉 AI 多维表《杰克知识管理规范》实时数据代理）。

治理标准页的数据源为钉钉 AI 多维表，前端通过本路由读取，刷新按钮触发重新拉取。
"""
import asyncio
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.deps import require_role
from kb_common.clients import dingtalk_client

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])

# 多维表字段名 -> 后端标准化键
_F_DOC_TYPE = "文档类型"
_F_CODE = "类型编号"  # 自动编号（DOC-YYYYMMDD-XXXX），多维表中该字段名为「类型编号」
_F_LINK = "规范链接"
_F_MAINTAINER = "维护人"
_F_DATE = "生效日期"
_F_VERSION = "版本号"
_F_STATUS = "文档状态"

# 治理标准缓存：读一次钉钉多维表要 300ms～数秒（限流重试时更久），
# 而每次点「知识治理」菜单都会打这个接口。TTL 内直接返回缓存，
# 页面「刷新」按钮带 refresh=true 强制重拉，兼顾响应速度与数据新鲜度。
_STANDARDS_TTL = 60.0
_standards_cache: dict[str, Any] = {"at": 0.0, "payload": None}
# 单飞锁：并发未命中时只放一个请求去拉钉钉，其余复用其结果
_standards_lock = asyncio.Lock()
# 后台刷新单飞标记：缓存过期时只允许一个后台刷新任务在飞
_standards_refresh: dict[str, bool] = {"running": False}


def _as_text(val: Any) -> str:
    """单选/文本等字段值统一转显示文本（兼容字符串或 {name} 结构）。"""
    if isinstance(val, dict):
        return str(val.get("name") or val.get("text") or val.get("link") or "")
    return "" if val is None else str(val)


def _as_date(val: Any) -> str:
    """日期字段值转 YYYY-MM-DD（兼容毫秒时间戳或字符串）。"""
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return ""
    return str(val or "")[:10]


async def _fetch_standards() -> dict[str, Any]:
    """实时读取钉钉多维表并标准化字段（不做缓存）。"""
    error = None
    records: list[dict[str, Any]] = []
    try:
        # 「系统配置」页保存的钉钉凭证即时生效（DB 优先）
        await dingtalk_client.sync_runtime_config()
        records = await dingtalk_client.list_aitable_records(
            dingtalk_client.STANDARDS_BASE_ID, dingtalk_client.STANDARDS_SHEET_ID
        )
    except Exception as e:
        error = str(e)

    # 收集维护人 userId，复用既有「userid -> 姓名」批量解析（带缓存）
    user_ids: list[str] = []
    for rec in records:
        for m in rec.get("fields", {}).get(_F_MAINTAINER) or []:
            uid = m.get("userId") or m.get("unionId") if isinstance(m, dict) else m
            if uid:
                user_ids.append(str(uid))
    name_map = await dingtalk_client.get_user_name_map(user_ids) if user_ids else {}

    items = []
    for rec in records:
        f = rec.get("fields", {})
        maintainers: list[str] = []
        for m in f.get(_F_MAINTAINER) or []:
            if isinstance(m, dict):
                # 多维表人员字段直接返回 {unionId, name}；name 缺失时回退 userid 解析
                name = m.get("name") or m.get("nickName") or name_map.get(
                    str(m.get("userId") or m.get("unionId") or "")
                )
                maintainers.append(str(name or m.get("unionId") or ""))
            else:
                maintainers.append(name_map.get(str(m)) or str(m))
        items.append({
            "record_id": rec.get("id"),
            "doc_type": _as_text(f.get(_F_DOC_TYPE)),
            "code": _as_text(f.get(_F_CODE)),
            "version": _as_text(f.get(_F_VERSION)),
            "status": _as_text(f.get(_F_STATUS)),
            "effective_date": _as_date(f.get(_F_DATE)),
            "link": _as_text(f.get(_F_LINK)),
            "maintainer": "、".join(dict.fromkeys(m for m in maintainers if m)) or "—",
        })

    return {
        "items": items,
        "total": len(items),
        "error": error,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def _schedule_standards_refresh() -> None:
    """后台单飞刷新治理标准缓存：失败保留旧数据，下次访问再试。"""
    if _standards_refresh["running"]:
        return
    _standards_refresh["running"] = True

    async def _run() -> None:
        try:
            payload = await _fetch_standards()
            if not payload.get("error"):
                _standards_cache["at"] = time.monotonic()
                _standards_cache["payload"] = payload
        finally:
            _standards_refresh["running"] = False

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:          # 不在事件循环中——放弃本次后台刷新
        _standards_refresh["running"] = False


@router.get("/standards")
async def get_standards(refresh: bool = Query(False, description="true=绕过缓存强制重拉钉钉多维表"),
                        u=Depends(require_role("super_admin", "admin", "editor", "viewer"))):
    """治理标准列表：读取钉钉 AI 多维表《杰克知识管理规范》。

    缓存策略（60s TTL + 过期后台刷新）：钉钉多维表一次调用在限流/抖动时可达数十秒，
    绝不能挡在页面渲染前面。因此
    - 命中新鲜缓存：直接返回（from_cache=true, stale=false）；
    - 缓存过期但存在：立刻返回旧数据，同时后台单飞刷新（stale=true）；
    - 完全没有缓存，或用户点「刷新」(refresh=true)：同步等一次（20s 超时 × 2 次重试）。
    出错时返回 200 + error 字段（沿用运营看板模式），且不写缓存，下次访问自动重试。
    """
    cached = _standards_cache["payload"]
    if cached is not None and not refresh:
        stale = time.monotonic() - _standards_cache["at"] >= _STANDARDS_TTL
        if stale:
            _schedule_standards_refresh()
        return {**cached, "from_cache": True, "stale": stale}

    async with _standards_lock:
        # 二次检查：等锁期间可能已被别的请求刷新
        cached = _standards_cache["payload"]
        if cached is not None and not refresh:
            return {**cached, "from_cache": True, "stale": False}
        payload = await _fetch_standards()
        if not payload.get("error"):
            _standards_cache["at"] = time.monotonic()
            _standards_cache["payload"] = payload
        return {**payload, "from_cache": False, "stale": False}
