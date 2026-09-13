"""知识运营：问答反馈（点赞/点踩/纠错）、问答明细、知识纠错工单。"""
import uuid as uuid_lib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import QaFeedback, User
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1/qa", tags=["qa"])

FEEDBACK_TYPES = {"helpful", "correct", "notfound"}
ERROR_TYPES = ["内容错误", "知识重复", "知识过期", "知识难理解", "知识不完整", "知识模板错误", "其它"]
CORRECTION_STATUS = {"pending", "processing", "resolved", "closed"}
STATUS_LABEL = {"pending": "待处理", "processing": "处理中", "resolved": "已解决", "closed": "已关闭"}


class FeedbackIn(BaseModel):
    feedback_type: str
    session_id: str | None = None
    message_id: str | None = None
    knowledge_title: str | None = None
    knowledge_url: str | None = None
    error_type: str | None = None
    content: str | None = None
    question: str | None = None


class CorrectionUpdate(BaseModel):
    status: str
    handler_note: str | None = None


def _parse_uuid(v: str | None) -> uuid_lib.UUID | None:
    if not v:
        return None
    try:
        return uuid_lib.UUID(v)
    except ValueError:
        return None


@router.post("/feedback")
async def submit_feedback(body: FeedbackIn, u=Depends(get_current_user),
                          s: AsyncSession = Depends(get_session)):
    """用户提交问答反馈：点赞(helpful)/纠错(correct)/没找到(notfound)。纠错类生成待处理工单。"""
    if body.feedback_type not in FEEDBACK_TYPES:
        raise HTTPException(400, "反馈类型无效")
    if body.feedback_type == "correct" and body.error_type and body.error_type not in ERROR_TYPES:
        raise HTTPException(400, "错误类型无效")

    fb = QaFeedback(
        user_id=u.id,
        session_id=_parse_uuid(body.session_id),
        message_id=_parse_uuid(body.message_id),
        feedback_type=body.feedback_type,
        knowledge_title=(body.knowledge_title or "").strip() or None,
        knowledge_url=(body.knowledge_url or "").strip() or None,
        error_type=body.error_type,
        content=(body.content or "").strip() or None,
        question=(body.question or "").strip() or None,
        # 纠错进入工单流待处理；点赞/没找到直接关闭
        status="pending" if body.feedback_type == "correct" else "closed",
    )
    s.add(fb)
    await s.commit()
    return {"ok": True, "id": str(fb.id), "status": fb.status}


@router.get("/details")
async def qa_details(
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    user: str | None = None,
    feedback: str | None = None,   # helpful | correct | notfound | none
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
    s: AsyncSession = Depends(get_session),
):
    """问答明细：用户问题 + 助手回答（含回答链路 steps、召回片段 retrieval、反馈），分页 + 多维过滤。"""
    # 口径：排除管理类账号，普通用户与钉钉免登/机器人自动建档用户的问答均入明细
    where = ["u.role NOT IN ('super_admin', 'admin')"]
    params: dict = {}
    if date_from:
        try:
            params["df"] = datetime.strptime(date_from[:10], "%Y-%m-%d")
            where.append("u.created_at >= :df")
        except ValueError:
            pass
    if date_to:
        try:
            params["dt"] = datetime.strptime(date_to[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            where.append("u.created_at <= :dt")
        except ValueError:
            pass
    if keyword:
        params["kw"] = f"%{keyword.strip()}%"
        where.append("(u.content ILIKE :kw OR a.acontent ILIKE :kw)")
    if user:
        params["un"] = f"%{user.strip()}%"
        where.append("usr.username ILIKE :un")
    if feedback:
        if feedback == "none":
            where.append("NOT EXISTS (SELECT 1 FROM qa_feedbacks f WHERE f.message_id = a.aid)")
        elif feedback in FEEDBACK_TYPES:
            params["fb"] = feedback
            where.append("EXISTS (SELECT 1 FROM qa_feedbacks f WHERE f.message_id = a.aid AND f.feedback_type = :fb)")
    where_sql = " AND ".join(where)

    # 每条用户消息关联同会话其后第一条助手消息（LATERAL）
    base_from = """
        FROM chat_messages u
        JOIN chat_sessions cs ON cs.id = u.session_id
        LEFT JOIN users usr ON usr.id = cs.user_id
        LEFT JOIN LATERAL (
            SELECT a2.id AS aid, a2.content AS acontent, a2.citations AS acitations,
                   a2.meta AS ameta, a2.detail AS adetail, a2.created_at AS acreated_at
            FROM chat_messages a2
            WHERE a2.session_id = u.session_id AND a2.role = 'assistant'
              AND a2.created_at >= u.created_at
            ORDER BY a2.created_at ASC LIMIT 1
        ) a ON true
    """
    total = (await s.execute(
        text(f"SELECT count(*) {base_from} WHERE {where_sql}"), params
    )).scalar() or 0

    params["lim"] = page_size
    params["off"] = (page - 1) * page_size
    rows = (await s.execute(text(f"""
        SELECT u.id AS qid, u.content AS question, u.created_at AS asked_at,
               a.aid, a.acontent AS answer, a.acitations AS citations,
               a.ameta AS meta, a.adetail AS detail,
               cs.id AS session_id, cs.title AS session_title,
               usr.id AS user_id, usr.username AS username
        {base_from}
        WHERE {where_sql}
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT :lim OFFSET :off
    """), params)).mappings().all()

    # 批量取这些回答的反馈
    aids = [r["aid"] for r in rows if r["aid"]]
    fb_map: dict = {}
    if aids:
        fb_rows = (await s.execute(
            select(QaFeedback).where(QaFeedback.message_id.in_(aids))
            .order_by(QaFeedback.created_at)
        )).scalars().all()
        for f in fb_rows:
            fb_map.setdefault(str(f.message_id), []).append({
                "feedback_type": f.feedback_type,
                "error_type": f.error_type,
                "content": f.content,
                "status": f.status,
            })

    items = []
    for r in rows:
        detail = r["detail"] or {}
        items.append({
            "question_id": str(r["qid"]),
            "message_id": str(r["aid"]) if r["aid"] else None,
            "session_id": str(r["session_id"]) if r["session_id"] else None,
            "session_title": r["session_title"],
            "username": r["username"] or "未知用户",
            "user_id": str(r["user_id"]) if r["user_id"] else None,
            "question": r["question"],
            "answer": r["answer"] or "",
            "meta": r["meta"] or "",
            "asked_at": r["asked_at"].strftime("%Y-%m-%d %H:%M:%S") if r["asked_at"] else None,
            "steps": detail.get("steps") or [],
            "retrieval": detail.get("retrieval") or [],
            "model": detail.get("model") or "",
            "duration_ms": detail.get("duration_ms"),
            "feedbacks": fb_map.get(str(r["aid"]), []),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/corrections")
async def list_corrections(
    keyword: str | None = None,
    error_type: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
    s: AsyncSession = Depends(get_session),
):
    """知识纠错工单列表（feedback_type=correct），支持知识标题/错误类型/状态过滤。"""
    q = select(QaFeedback, User.username).outerjoin(User, User.id == QaFeedback.user_id).where(
        QaFeedback.feedback_type == "correct"
    )
    cnt_q = select(func.count()).select_from(QaFeedback).where(QaFeedback.feedback_type == "correct")
    if keyword:
        kw = f"%{keyword.strip()}%"
        q = q.where(QaFeedback.knowledge_title.ilike(kw) | QaFeedback.content.ilike(kw) | QaFeedback.question.ilike(kw))
        cnt_q = cnt_q.where(QaFeedback.knowledge_title.ilike(kw) | QaFeedback.content.ilike(kw) | QaFeedback.question.ilike(kw))
    if error_type:
        q = q.where(QaFeedback.error_type == error_type)
        cnt_q = cnt_q.where(QaFeedback.error_type == error_type)
    if status:
        q = q.where(QaFeedback.status == status)
        cnt_q = cnt_q.where(QaFeedback.status == status)

    total = (await s.execute(cnt_q)).scalar() or 0
    rows = (await s.execute(
        q.order_by(QaFeedback.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    )).all()

    # 处理人姓名
    handler_ids = [r[0].handler_id for r in rows if r[0].handler_id]
    handler_map: dict = {}
    if handler_ids:
        hs = (await s.execute(select(User).where(User.id.in_(handler_ids)))).scalars().all()
        handler_map = {str(h.id): h.username for h in hs}

    items = []
    for fb, username in rows:
        items.append({
            "id": str(fb.id),
            "knowledge_title": fb.knowledge_title or "（未指定知识）",
            "knowledge_url": fb.knowledge_url or "",
            "question": fb.question or "",
            "error_type": fb.error_type or "其它",
            "content": fb.content or "",
            "status": fb.status,
            "status_label": STATUS_LABEL.get(fb.status, fb.status),
            "applicant": username or "未知用户",
            "handler": handler_map.get(str(fb.handler_id)) if fb.handler_id else None,
            "handler_note": fb.handler_note or "",
            "created_at": fb.created_at.strftime("%Y-%m-%d %H:%M") if fb.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "error_types": ERROR_TYPES}


@router.put("/corrections/{cid}")
async def update_correction(cid: str, body: CorrectionUpdate,
                            u=Depends(require_role("super_admin", "admin")),
                            s: AsyncSession = Depends(get_session)):
    """处理纠错工单：更新状态（处理人自动记为当前操作人）与处理备注。"""
    if body.status not in CORRECTION_STATUS:
        raise HTTPException(400, "状态无效")
    try:
        fid = uuid_lib.UUID(cid)
    except ValueError:
        raise HTTPException(400, "无效的工单 ID")
    fb = (await s.execute(select(QaFeedback).where(QaFeedback.id == fid))).scalar_one_or_none()
    if not fb:
        raise HTTPException(404, "工单不存在")
    fb.status = body.status
    fb.handler_id = u.id
    if body.handler_note is not None:
        fb.handler_note = body.handler_note.strip() or None
    await s.commit()
    return {"ok": True, "status": fb.status}
