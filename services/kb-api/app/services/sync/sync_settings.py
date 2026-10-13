"""同步模块凭据解析：DB 系统配置（Setting 表）优先，回退 .env Settings。

平台钉钉凭据由 系统配置页（settings_route）维护在 DB 中，
.env 里通常为空。同步路由与引擎必须统一走此解析，否则拿到空凭据，
钉钉会报 invalidClientIdOrSecret。
"""
from __future__ import annotations

from sqlalchemy import select

from kb_common.config import get_settings
from kb_common.models import Setting

# 同步模块关心的可配置项（与 settings_route.KEYS 保持一致）
SYNC_SETTING_KEYS = (
    "dingtalk_app_key",
    "dingtalk_app_secret",
    "dingtalk_operator_union_id",
)


def load_sync_settings(db) -> dict[str, str]:
    """返回 key→value；db 为同步 Session（SyncSessionLocal）。"""
    s = get_settings()
    vals: dict[str, str] = {k: (getattr(s, k, "") or "") for k in SYNC_SETTING_KEYS}
    try:
        rows = db.execute(
            select(Setting).where(Setting.key.in_(SYNC_SETTING_KEYS))
        ).scalars().all()
        for row in rows:
            if row.value and row.value.strip():
                vals[row.key] = row.value.strip()
    except Exception:  # noqa: BLE001 — DB 查询失败时退回 .env
        pass
    return vals


def make_dingtalk_client(db, operator_union_id: str | None = None):
    """用解析后的凭据构建同步 DingTalkClient。

    operator_union_id：按同步源 owner 维度传入（权限与 owner 一致）；
    不传回退全局 dingtalk_operator_union_id 服务账号（历史行为）。
    """
    from app.services.sync.dingtalk_sync_client import DingTalkClient

    vals = load_sync_settings(db)
    return DingTalkClient(
        vals["dingtalk_app_key"],
        vals["dingtalk_app_secret"],
        operator_union_id or vals["dingtalk_operator_union_id"],
    )


def make_library_backend(source):
    """构建本地文档库（document-libraries）同步后端。

    dataset_id 存本地文档库 ID；source 可为 SyncSource 对象或 dict（路由层创建/更新时）。
    """
    from app.services.sync.library_backend import LibraryBackend
    if isinstance(source, dict):
        dataset_id = source.get("dataset_id") or ""
        src_id = source.get("id", "?")
    else:
        dataset_id = getattr(source, "dataset_id", "") or ""
        src_id = getattr(source, "id", "?")
    try:
        library_id = int(dataset_id)
    except (ValueError, TypeError):
        raise ValueError(f"同步源 {src_id} 的文档库 ID 无效：{dataset_id!r}")
    return LibraryBackend(library_id)
