"""同步模块凭据解析：DB 系统配置（Setting 表）优先，回退 .env Settings。

平台钉钉/Dify 凭据由 系统配置页（settings_route）维护在 DB 中，
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
    "dify_base_url",
    "dify_api_key",
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


def make_dingtalk_client(db):
    """用解析后的凭据构建同步 DingTalkClient。"""
    from app.services.sync.dingtalk_sync_client import DingTalkClient

    vals = load_sync_settings(db)
    return DingTalkClient(
        vals["dingtalk_app_key"],
        vals["dingtalk_app_secret"],
        vals["dingtalk_operator_union_id"],
    )


def make_dify_client(db):
    """用解析后的凭据构建同步 DifyClient。"""
    from app.services.sync.dify_sync_client import DifyClient

    vals = load_sync_settings(db)
    return DifyClient(vals["dify_base_url"], vals["dify_api_key"])
