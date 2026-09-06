"""知识治理路由：治理标准（钉钉 AI 多维表《杰克知识管理规范》实时数据代理）。

治理标准页的数据源为钉钉 AI 多维表，前端通过本路由读取，刷新按钮触发重新拉取。
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

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


@router.get("/standards")
async def get_standards(u=Depends(require_role("super_admin", "admin", "editor", "viewer"))):
    """治理标准列表：实时读取钉钉 AI 多维表《杰克知识管理规范》。

    出错时返回 200 + error 字段（沿用运营看板模式），前端保留旧数据并提示。
    """
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
