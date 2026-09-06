"""智能问答会话管理：会话历史、消息隔离、每个会话独立记忆文档。"""
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import ChatSession, ChatMessage
from app.deps import get_current_user
from kb_common.models import User

router = APIRouter(prefix="/api/v1/chat-sessions", tags=["chat-sessions"])

MEMORY_MAX_CHARS = 4000   # 记忆文档上限，超出后保留最近部分
ANSWER_IN_MEMORY = 300    # 记忆文档中每条回答的截断长度


class SessionIn(BaseModel):
    title: str = "新会话"


class TurnIn(BaseModel):
    """保存一轮问答：问题 + 回答 + 引用 + 元信息 + 改写上下文。"""
    question: str
    answer: str
    citations: list[str] = []
    meta: str = ""
    last_query: str = ""
    last_answer: str = ""
    detail: dict | None = None  # 回答链路/召回片段 {steps, retrieval, model, duration_ms}


def _session_dict(s: ChatSession, msg_count: int = 0) -> dict:
    return {
        "id": str(s.id),
        "title": s.title,
        "memory": s.memory,
        "last_query": s.last_query,
        "last_answer": s.last_answer,
        "message_count": msg_count,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def _get_owned(session_id: str, user: User, s: AsyncSession) -> ChatSession:
    try:
        sid = uuid_lib.UUID(session_id)
    except ValueError:
        raise HTTPException(400, "无效的会话 ID")
    row = (await s.execute(
        select(ChatSession).where(ChatSession.id == sid, ChatSession.user_id == user.id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "会话不存在")
    return row


@router.get("")
async def list_sessions(u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """当前用户的会话列表（按更新时间倒序）。"""
    rows = (await s.execute(
        select(ChatSession)
        .where(ChatSession.user_id == u.id)
        .order_by(ChatSession.updated_at.desc())
    )).scalars().all()
    out = []
    for r in rows:
        cnt = (await s.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.session_id == r.id)
        )).scalar() or 0
        out.append(_session_dict(r, cnt))
    return out


@router.post("")
async def create_session(body: SessionIn, u=Depends(get_current_user),
                         s: AsyncSession = Depends(get_session)):
    sess = ChatSession(user_id=u.id, title=body.title.strip() or "新会话")
    s.add(sess)
    await s.commit()
    await s.refresh(sess)
    return _session_dict(sess)


@router.put("/{session_id}")
async def rename_session(session_id: str, body: SessionIn,
                         u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    row = await _get_owned(session_id, u, s)
    title = body.title.strip()
    if title:
        row.title = title[:200]
    await s.commit()
    await s.refresh(row)
    return _session_dict(row)


@router.delete("/{session_id}")
async def delete_session(session_id: str, u=Depends(get_current_user),
                         s: AsyncSession = Depends(get_session)):
    row = await _get_owned(session_id, u, s)
    await s.delete(row)  # ON DELETE CASCADE 级联删除消息
    await s.commit()
    return {"ok": True}


@router.get("/{session_id}/messages")
async def list_messages(session_id: str, u=Depends(get_current_user),
                        s: AsyncSession = Depends(get_session)):
    row = await _get_owned(session_id, u, s)
    msgs = (await s.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == row.id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )).scalars().all()
    return {
        "session": _session_dict(row, len(msgs)),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "meta": m.meta or "",
                "detail": m.detail or None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.post("/{session_id}/turn")
async def save_turn(session_id: str, body: TurnIn,
                    u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """保存一轮问答：写入用户/助手消息，首问生成标题，更新记忆文档与上下文。"""
    row = await _get_owned(session_id, u, s)
    question = body.question.strip()
    answer = body.answer.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    # 标题：首条用户消息确定，后续轮次不覆盖
    existing_count = (await s.execute(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == row.id)
    )).scalar() or 0
    if existing_count == 0:
        row.title = question[:50]

    # 写入消息
    user_msg = ChatMessage(session_id=row.id, role="user", content=question)
    assistant_msg = ChatMessage(
        session_id=row.id, role="assistant", content=answer,
        citations=body.citations or [], meta=body.meta or None,
        detail=body.detail or None,
    )
    s.add(user_msg)
    s.add(assistant_msg)
    await s.flush()  # 取消息 ID（供前端反馈/纠错关联）

    # 记忆文档：滚动追加「问/答」摘要，超上限保留最近内容
    ans_brief = answer.replace("\n", " ")[:ANSWER_IN_MEMORY]
    fragment = f"问：{question}\n答：{ans_brief}\n\n"
    memory = (row.memory or "") + fragment
    if len(memory) > MEMORY_MAX_CHARS:
        memory = memory[-MEMORY_MAX_CHARS:]
    row.memory = memory

    # 多轮上下文
    row.last_query = body.last_query or question
    row.last_answer = body.last_answer or answer

    await s.commit()
    return {"ok": True, "user_message_id": str(user_msg.id), "assistant_message_id": str(assistant_msg.id)}
