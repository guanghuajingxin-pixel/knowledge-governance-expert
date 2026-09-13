"""钉钉企业内部机器人：Stream 长连接收消息 → 无历史问答 → markdown 回复。

- Stream 模式出站长连接（kb-api 进程内后台 task），内网服务器无需公网入口；
- 每条消息 session_id='' → 一次性 thread，不携带/不写入会话上下文（钉钉侧无历史语义）；
- 运营记录与上下文分离：每位钉钉用户一个固定会话（标题「钉钉机器人·姓名」），
  仅用于问答明细/调用日志落库，不参与问答上下文组装；
- 并发信号量 2（对齐 LiteLLM 网关实测并发上限），排队等待超阈值先回「检索中」提示；
- 回复优先消息回调自带 sessionWebhook，失效降级 OpenAPI（单聊 oTo / 群 groupMessages）；
- fail fast：开关/凭证缺失不启动，原因经 get_status() 暴露给系统配置页。
"""
import asyncio
import logging
import re
import time
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from kb_common.clients import dingtalk_client
from kb_common.database import SessionLocal
from kb_common.models import ChatMessage, ChatSession, Setting

logger = logging.getLogger(__name__)

_QA_CONCURRENCY = 2            # 对齐 LiteLLM 网关实测并发上限
_ACK_WAIT_NOTICE_SECONDS = 8   # 排队等待超该秒数先回「检索中」提示
_MAX_REPLY_CHARS = 4500        # 钉钉 markdown 单条上限（超出截断引导去 /qa）
_SEEN_TTL = 600.0              # msgId 幂等去重窗口（秒）

_state: dict[str, Any] = {"enabled": False, "running": False, "connected": False,
                          "last_error": "", "started_at": None}
_task: asyncio.Task | None = None
_sem: asyncio.Semaphore | None = None
_seen: dict[str, float] = {}


def get_status() -> dict:
    """机器人运行状态（系统配置页展示）。"""
    return {**_state, "qa_concurrency": _QA_CONCURRENCY}


async def _settings_map(keys: list[str]) -> dict[str, str]:
    async with SessionLocal() as s:
        rows = (await s.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    return {r.key: (r.value or "") for r in rows}


async def refresh_bot() -> None:
    """按 DB 配置热启停机器人（lifespan 启动与配置保存时调用）。"""
    global _task, _sem
    cfg = await _settings_map(["dingtalk_bot_enabled", "dingtalk_app_key", "dingtalk_app_secret"])
    enabled = cfg.get("dingtalk_bot_enabled", "").strip().lower() in ("1", "true", "yes", "on")
    ready = bool(cfg.get("dingtalk_app_key") and cfg.get("dingtalk_app_secret"))
    _state["enabled"] = enabled
    if not enabled:
        await stop_bot()
        return
    if not ready:
        _state["last_error"] = "钉钉 AppKey/AppSecret 未配置，机器人未启动"
        await stop_bot()
        return
    if _task and not _task.done():
        return
    _sem = asyncio.Semaphore(_QA_CONCURRENCY)
    _state["last_error"] = ""
    _task = asyncio.create_task(_run_forever(cfg), name="dingtalk-bot-stream")


async def stop_bot() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except BaseException:  # noqa: BLE001 - 取消路径吞所有异常
            pass
    _task = None
    _state.update(running=False, connected=False)


async def _run_forever(cfg: dict[str, str]) -> None:
    """Stream 长连接主循环：断线/异常 5s 后重建客户端重连。"""
    try:
        from dingtalk_stream import ChatbotMessage, Credential, DingTalkStreamClient
    except ImportError as e:
        _state["last_error"] = f"缺少 dingtalk-stream 依赖：{e}"
        logger.error("钉钉机器人未启动：%s", _state["last_error"])
        return
    while True:
        client = DingTalkStreamClient(Credential(cfg["dingtalk_app_key"], cfg["dingtalk_app_secret"]))
        client.register_callback_handler(ChatbotMessage.TOPIC, _BotHandler())
        _state.update(running=True, connected=True,
                      started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("钉钉机器人 Stream 长连接已启动")
        try:
            await client.start()
            _state["last_error"] = "Stream 连接被对端关闭，5s 后重连"
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            _state["last_error"] = f"Stream 连接异常：{e.__class__.__name__}: {e}"
            logger.exception("钉钉机器人 Stream 连接异常")
        _state["connected"] = False
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------------------
from dingtalk_stream import AckMessage, ChatbotHandler, ChatbotMessage


class _BotHandler(ChatbotHandler):
    """Stream 回调处理：立即 ACK，消息异步处理，不阻塞接收循环。"""

    async def process(self, callback):
        try:
            msg = ChatbotMessage.from_dict(callback.data)
        except Exception:  # noqa: BLE001
            logger.exception("解析机器人回调失败")
            return AckMessage.STATUS_OK, "OK"
        asyncio.create_task(self._safe_handle(msg))
        return AckMessage.STATUS_OK, "OK"

    async def _safe_handle(self, msg: ChatbotMessage) -> None:
        try:
            await _handle_message(msg)
        except Exception:  # noqa: BLE001
            logger.exception("钉钉机器人消息处理失败 msg=%s", getattr(msg, "message_id", ""))


def _prune_seen(now: float) -> None:
    for k in [k for k, v in _seen.items() if now - v > _SEEN_TTL]:
        _seen.pop(k, None)


async def _handle_message(msg: Any) -> None:
    text = ((msg.text.content if getattr(msg, "text", None) else "") or "").strip()
    msg_id = getattr(msg, "message_id", "") or ""
    now = time.monotonic()
    _prune_seen(now)
    if msg_id:
        if msg_id in _seen:
            return  # 钉钉重试投递幂等去重
        _seen[msg_id] = now
    if not text:
        await _reply(msg, "请发送文字问题，我会基于企业知识库为你检索作答。")
        return

    cfg = await _settings_map(["dingtalk_corp_id", "dingtalk_bot_allow_users"])
    allow = {x.strip() for x in cfg.get("dingtalk_bot_allow_users", "").split(",") if x.strip()}
    staff_id = (getattr(msg, "sender_staff_id", "") or "").strip()
    if allow and staff_id not in allow:
        await _reply(msg, "抱歉，机器人问答暂未对你开放，请联系管理员。")
        return
    corp_id = (getattr(msg, "sender_corp_id", "") or getattr(msg, "chatbot_corp_id", "")
               or cfg.get("dingtalk_corp_id", "")).strip()

    from app.services.dingtalk_identity import resolve_user
    async with SessionLocal() as s:
        try:
            user, binding = await resolve_user(
                s, corp_id, staff_id or (getattr(msg, "sender_id", "") or ""),
                dt_name=getattr(msg, "sender_nick", "") or "")
        except RuntimeError as e:
            await _reply(msg, str(e))
            return
        display = binding.dt_name or getattr(msg, "sender_nick", "") or user.username

        # 并发保护：排队等待超阈值先提示，避免静默
        sem = _sem or asyncio.Semaphore(_QA_CONCURRENCY)
        reply_md: str | None = None
        try:
            await asyncio.wait_for(sem.acquire(), timeout=_ACK_WAIT_NOTICE_SECONDS)
        except asyncio.TimeoutError:
            await _reply(msg, "当前提问较多，已排队检索知识，请稍候…")
            await sem.acquire()
        try:
            result, err = await _run_qa(text, user, s)
            if err:
                await _reply(msg, err)
                return
            if not result:
                await _reply(msg, "问答服务暂不可用，请稍后重试。")
                return
            await _record(s, user, display, text, result)
            reply_md = _build_reply_md(result)
        finally:
            sem.release()

    await _reply(msg, reply_md or "问答服务暂不可用，请稍后重试。")


async def _run_qa(query: str, user: Any, s: Any) -> tuple[dict | None, str | None]:
    """复用网页问答链路：空 session_id → 一次性 thread（无历史）。"""
    from app.routes.search import ChatIn, _prepare_qa, _qa_events
    body = ChatIn(query=query, session_id="")
    try:
        qa = await _prepare_qa(body, user, s)
    except HTTPException as e:
        return None, str(e.detail)
    result: dict | None = None
    err: str | None = None
    async for ev in _qa_events(qa):
        if ev["type"] == "final":
            result = ev["result"]
        elif ev["type"] == "config_error":
            err = ev.get("message") or "问答服务暂不可用，请稍后重试。"
    return result, err


async def _record(s: Any, user: Any, display: str, query: str, result: dict) -> None:
    """落运营记录：固定会话 + 消息 + 调用日志（不参与问答上下文）。"""
    from app.routes.search import _log_usage
    title = f"钉钉机器人·{display}"[:200]
    sess = (await s.execute(
        select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.title == title)
    )).scalar_one_or_none()
    if not sess:
        sess = ChatSession(user_id=user.id, title=title)
        s.add(sess)
        await s.flush()
    answer = (result.get("answer") or "").strip()
    cites = result.get("citations") or []
    s.add(ChatMessage(session_id=sess.id, role="user", content=query))
    s.add(ChatMessage(
        session_id=sess.id, role="assistant", content=answer,
        citations=[str(c.get("document_title") or "") for c in cites],
        meta=result.get("engine") or "deerflow",
        detail={"scene": "dingtalk_bot"},
    ))
    await s.commit()
    _log_usage(user.id, "dingtalk_bot", query, len(cites),
               [str(c.get("document_id", "")) for c in cites],
               [str(c.get("document_title", "")) for c in cites])


def _build_reply_md(result: dict) -> str:
    answer = (result.get("answer") or "").strip() or "（空回答）"
    md = to_dingtalk_markdown(answer)
    cites = result.get("citations") or []
    if cites:
        lines = []
        for i, c in enumerate(cites[:5], 1):
            t = str(c.get("document_title") or "未知文档")
            u = str(c.get("url") or "")
            lines.append(f"{i}. [{t}]({u})" if u else f"{i}. {t}")
        md += "\n\n**出处**：\n" + "\n".join(lines)
    return md


async def _reply(msg: Any, text: str, title: str = "问答结果") -> None:
    webhook = getattr(msg, "session_webhook", "") or ""
    if webhook:
        try:
            await dingtalk_client.reply_session_webhook(webhook, title, text)
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("sessionWebhook 回复失败，降级 OpenAPI：%s", e)
    conv_type = (getattr(msg, "conversation_type", "") or "").strip()
    try:
        if conv_type == "1":
            await dingtalk_client.send_markdown_message(
                [getattr(msg, "sender_staff_id", "") or getattr(msg, "sender_id", "")], title, text)
        else:
            await dingtalk_client.send_group_markdown(getattr(msg, "conversation_id", "") or "", title, text)
    except Exception:  # noqa: BLE001
        logger.exception("钉钉机器人回复失败（全部通道）")


# ---------------------------------------------------------------------------
# 网页 markdown → 钉钉 markdown 转换层
# ---------------------------------------------------------------------------
_SEP_CELL = re.compile(r"^:?-{2,}:?$")
_IMG = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def to_dingtalk_markdown(md: str, max_chars: int = _MAX_REPLY_CHARS) -> str:
    """钉钉 sampleMarkdown 不支持表格/稳定代码块/内网图片，按规则降级。"""
    out: list[str] = []
    in_code = False
    header: list[str] | None = None
    for raw in md.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(_SEP_CELL.match(c or "-") for c in cells):
                continue  # 表头分隔行
            if header is None:
                header = cells
                continue
            label = cells[0] if cells else ""
            rest = [c for c in cells[1:] if c]
            out.append(f"- **{label}**：{'、'.join(rest)}" if rest else f"- {label}")
            continue
        header = None  # 离开表格区域
        if not stripped:
            out.append("")
            continue
        line = _IMG.sub(lambda m: f"〔图：{m.group(1) or '示意图'}〕", line)
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if in_code:
        text += "\n```"  # 未闭合围栏兜底（仅文本展示，不保证等宽）
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n…回答较长，全文请见知识治理平台 /qa"
    return text
