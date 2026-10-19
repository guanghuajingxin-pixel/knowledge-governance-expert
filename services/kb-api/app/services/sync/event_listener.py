"""钉钉知识库变更事件监听：Stream 长连接 → 按源去抖 → 整源增量编目（自动同步）。

取消定时编目后的自动同步触发器：
- 钉钉开放平台 Stream 模式长连接（企业内部应用，复用机器人同一套 AppKey/Secret）；
- 订阅文档/知识库变更事件，事件只作为「变化信号」——实际同步内容由
  编目 run_catalog 的增量 diff 决定（幂等），不解析事件业务粒度；
- 事件里能匹配到任一启用同步源的 workspace_id 即触发该源编目（trigger="auto"）；
- 同一源 N 秒窗口内多次事件合并为一次编目（threading.Timer 去抖，无 loop 依赖，
  事件风暴如批量移动节点不会打爆编目）；
- 静默期兜底：编目因编辑静默跳过时，可注册静默窗口后的单次补跑（schedule_recheck）；
- fail-soft：凭据缺失/SDK 缺失/连接失败只记状态与告警，不拖垮 kb-api。

订阅 topic 可经配置覆盖：Setting 表 dingtalk_sync_event_topics（逗号分隔 eventType），
回退 .env dingtalk_sync_event_topics，再回退代码默认列表；官方事件名以钉钉开发者
后台「事件与回调」实际提供为准，联调期靠日志修正。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from sqlalchemy import select

from kb_common.config import get_settings
from kb_common.models import Setting
from dingtalk_stream import CallbackHandler

logger = logging.getLogger(__name__)

# 默认订阅的文档/知识库事件（Stream topic = /v1.0/event/{eventType}）。
# 控制台未提供的事件订阅不生效也不报错；可在系统配置 dingtalk_sync_event_topics 覆盖。
DEFAULT_EVENT_TOPICS: tuple[str, ...] = (
    "doc_spaces_node_change",     # 知识库节点变更（新增/编辑/删除/移动，如控制台提供）
    "doc_node_edited",            # 文档编辑
    "drive_file_been_changed",    # 钉盘/存储文件变更
    "doc_spaces_team_change",     # 知识库小组变更（弱信号，兜底）
)

# 事件匹配与去抖的可配置项
_SETTING_TOPICS = "dingtalk_sync_event_topics"
_SETTING_DEBOUNCE = "dingtalk_sync_debounce_seconds"
_DEFAULT_DEBOUNCE_SECONDS = 30.0

_state: dict[str, Any] = {"enabled": False, "running": False, "connected": False,
                          "last_error": "", "started_at": None, "topics": ()}
_task: asyncio.Task | None = None
_debounce_lock = threading.Lock()
_timers: dict[int, threading.Timer] = {}   # source_id -> 待触发编目定时器


def get_status() -> dict:
    """监听器运行状态（运维排查用）。"""
    return dict(_state)


async def _resolve_topics() -> list[str]:
    """订阅事件列表：Setting 表 > .env > 默认列表。"""
    from kb_common.database import SessionLocal
    raw = (get_settings().dingtalk_sync_event_topics or "").strip()
    try:
        async with SessionLocal() as s:
            row = (await s.execute(
                select(Setting).where(Setting.key == _SETTING_TOPICS))).scalar_one_or_none()
        if row and row.value and row.value.strip():
            raw = row.value.strip()
    except Exception:  # noqa: BLE001 — 配置读取失败回退 .env
        pass
    topics = [t.strip() for t in raw.split(",") if t.strip()]
    return list(topics or DEFAULT_EVENT_TOPICS)


def _debounce_seconds() -> float:
    try:
        return max(5.0, float(get_settings().dingtalk_sync_debounce_seconds
                              or _DEFAULT_DEBOUNCE_SECONDS))
    except (TypeError, ValueError):
        return _DEFAULT_DEBOUNCE_SECONDS


def schedule_catalog(source_id: int, delay: float | None = None) -> None:
    """注册 source_id 的去抖编目：窗口内重复调用合并为一次（线程安全）。"""
    delay = _debounce_seconds() if delay is None else max(1.0, float(delay))
    with _debounce_lock:
        old = _timers.pop(source_id, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(delay, _fire_catalog, args=(source_id,))
        timer.daemon = True
        _timers[source_id] = timer
        timer.start()


def schedule_recheck(source_id: int, delay: float) -> None:
    """静默期兜底补查：指定延迟后重跑编目（与事件去抖共用计时器，重复预约自动合并）。"""
    schedule_catalog(source_id, delay)


def _fire_catalog(source_id: int) -> None:
    with _debounce_lock:
        _timers.pop(source_id, None)
    from .scheduler import _direct_executor
    from .catalog import run_catalog
    logger.info("钉钉事件触发自动编目 source_id=%s", source_id)
    _direct_executor.submit(run_catalog, source_id, "auto", "")


def cancel_pending() -> None:
    """停机时取消所有待触发编目。"""
    with _debounce_lock:
        for timer in _timers.values():
            timer.cancel()
        _timers.clear()


def _match_sources(blob: str) -> list[int]:
    """事件全文与启用同步源的 workspace_id 做包含匹配（ID 足够长，误报可忽略）。"""
    from kb_common.models import SyncSource
    from .sync_database import SyncSessionLocal
    hits: list[int] = []
    try:
        with SyncSessionLocal() as db:
            sources = db.query(SyncSource).filter(SyncSource.enabled.is_(True)).all()
            hits = [s.id for s in sources
                    if not s.import_once and s.workspace_id and s.workspace_id in blob]
    except Exception:  # noqa: BLE001 — 匹配失败只告警，不阻塞事件通道
        logger.exception("匹配钉钉事件对应同步源失败")
    return hits


class _DocEventHandler(CallbackHandler):
    """文档/知识库事件回调：立即 ACK，匹配与编目调度在线程池完成，不阻塞接收循环。

    必须继承 SDK 的 CallbackHandler：StreamClient.start() 的 pre_start() 会对每个
    已注册 handler 调 handler.pre_start()（基类默认空实现），裸类会 AttributeError。
    """

    async def process(self, callback) -> tuple[str, str]:
        from dingtalk_stream import AckMessage
        try:
            data = dict(callback.data or {})
        except Exception:  # noqa: BLE001
            data = {}
        event_type = str(data.get("eventType") or data.get("EventType") or "unknown")
        try:
            blob = str(data)  # 全文序列化后做 workspace 子串匹配（不依赖事件字段名）
            hits = _match_sources(blob)
            if hits:
                logger.info("收到钉钉文档事件 %s，命中同步源 %s", event_type, hits)
                for sid in hits:
                    schedule_catalog(sid)
            else:
                logger.info("收到钉钉文档事件 %s（未命中任何同步源，忽略）", event_type)
        except Exception:  # noqa: BLE001 — 事件处理失败只告警，不影响通道
            logger.exception("处理钉钉文档事件失败 type=%s", event_type)
        return AckMessage.STATUS_OK, "OK"


async def refresh_listener() -> None:
    """按配置热启停事件监听（lifespan 启动调用）。"""
    global _task
    from kb_common.database import SessionLocal
    cfg: dict[str, str] = {}
    async with SessionLocal() as s:
        rows = (await s.execute(select(Setting).where(
            Setting.key.in_(["dingtalk_app_key", "dingtalk_app_secret"])))).scalars().all()
        cfg = {r.key: (r.value or "") for r in rows}
    s = get_settings()
    app_key = (cfg.get("dingtalk_app_key") or s.dingtalk_app_key or "").strip()
    app_secret = (cfg.get("dingtalk_app_secret") or s.dingtalk_app_secret or "").strip()
    _state["enabled"] = True
    if not (app_key and app_secret):
        _state["last_error"] = "钉钉 AppKey/AppSecret 未配置，知识库变更监听未启动（自动同步不可用，手动同步不受影响）"
        logger.warning(_state["last_error"])
        await stop_listener()
        return
    if _task and not _task.done():
        return
    topics = await _resolve_topics()
    _state.update(topics=tuple(topics), last_error="")
    _task = asyncio.create_task(_run_forever(app_key, app_secret, topics),
                                name="dingtalk-sync-event-stream")


async def stop_listener() -> None:
    global _task
    from app.services.dingtalk_bot import stop_stream_task
    task, _task = _task, None
    # 同 dingtalk_bot：SDK 吞 CancelledError，必须双刀 cancel + 有界等待，
    # 否则 uvicorn 热重载的 shutdown 会永久挂死、旧进程泄漏 PG 连接。
    if not await stop_stream_task(task):
        logger.warning("钉钉知识库变更监听任务未确认退出（SDK 吞取消），已放弃等待；进程退出时随之消亡")
    cancel_pending()
    _state.update(running=False, connected=False)


async def _run_forever(app_key: str, app_secret: str, topics: list[str]) -> None:
    """Stream 长连接主循环：断线/异常 5s 后重建客户端重连（模式同 dingtalk_bot）。"""
    try:
        from dingtalk_stream import Credential, DingTalkStreamClient
    except ImportError as e:
        _state["last_error"] = f"缺少 dingtalk-stream 依赖：{e}"
        logger.error("知识库变更监听未启动：%s", _state["last_error"])
        return
    handler = _DocEventHandler()
    while True:
        client = DingTalkStreamClient(Credential(app_key, app_secret))
        for topic in topics:
            client.register_callback_handler(f"/v1.0/event/{topic}", handler)
        _state.update(running=True, connected=True,
                      started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("钉钉知识库变更监听已启动，订阅事件: %s", ", ".join(topics))
        try:
            await client.start()
            _state["last_error"] = "Stream 连接被对端关闭，5s 后重连"
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            _state["last_error"] = f"Stream 连接异常：{e.__class__.__name__}: {e}"
            logger.exception("钉钉知识库变更监听连接异常")
        _state["connected"] = False
        await asyncio.sleep(5)
