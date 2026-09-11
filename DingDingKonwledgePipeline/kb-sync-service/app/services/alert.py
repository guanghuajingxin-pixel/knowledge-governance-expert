"""钉钉群自定义机器人告警"""
from __future__ import annotations

import httpx
from loguru import logger

from ..config import settings


def send_alert(title: str, content: str) -> bool:
    webhook = settings.dingtalk_webhook
    if not webhook:
        return False
    text = f"{title}\n{content}"
    try:
        resp = httpx.post(webhook, json={"msgtype": "text", "text": {"content": text}}, timeout=10)
        if resp.status_code >= 400:
            logger.warning(f"告警发送失败 HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"告警发送异常: {exc}")
        return False


def alert_sync_failure(source_name: str, summary: dict) -> None:
    failed = summary.get("failed", 0)
    if failed < settings.alert_failure_threshold:
        return
    content = (f"同步源: {source_name}\n"
               f"结果: {summary.get('status')}\n"
               f"文档总数: {summary.get('total', 0)}\n"
               f"失败数量: {failed}\n"
               f"详情: {summary.get('message', '')}")
    send_alert("钉钉知识库同步告警", content)
