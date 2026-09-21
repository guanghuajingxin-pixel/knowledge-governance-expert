"""敏感操作审计写入：重置密码 / 解绑钉钉 / 角色变更 / 自主改密等留痕（audit_logs 表）。

写入失败只记日志不抛异常——审计是旁路能力，不能因为审计表故障阻断主业务；
但会有 kge 日志告警（logger.error），运维可据此发现审计链路断裂。
"""
import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.models import AuditLog

logger = logging.getLogger(__name__)


def _client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


async def write_audit(s: AsyncSession, *, actor_id, action: str, target_type: str,
                      target_id: str | None = None, detail: dict | None = None,
                      request: Request | None = None, commit: bool = True) -> None:
    row = AuditLog(
        actor_id=actor_id,
        action=action[:64],
        target_type=target_type[:32],
        target_id=(target_id or None),
        detail=detail,
        ip=_client_ip(request) or None,
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
    )
    s.add(row)
    if commit:
        try:
            await s.commit()
        except Exception:  # noqa: BLE001 — 审计旁路：失败告警但不阻断主流程
            await s.rollback()
            logger.error("审计写入失败 action=%s target=%s/%s", action, target_type, target_id,
                         exc_info=True)
