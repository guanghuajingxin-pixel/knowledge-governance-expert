from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import FaqEntry, KnowledgeBase
from app.deps import get_current_user, require_role
from app.services import faq_index, faq_import
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq", tags=["faq-entry"])

class EntryIn(BaseModel):
    question: str
    answer: str
    keywords: list[str] = []
    directory_id: uuid.UUID | None = None

class EntryUpdate(BaseModel):
    """部分更新：仅提供的字段会被写入。"""
    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None
    directory_id: uuid.UUID | None = None

@router.post("/knowledge-bases/{kb_id}/entries")
async def create(kb_id: uuid.UUID, body: EntryIn, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    e = FaqEntry(kb_id=kb_id, directory_id=body.directory_id, question=body.question,
                 answer=body.answer, keywords=body.keywords, status="DRAFT")
    s.add(e); await s.commit(); await s.refresh(e)
    kb = await s.get(KnowledgeBase, kb_id)
    await faq_index.index_entry(kb, e)
    e.status = "INDEXED"; await s.commit()
    return {"id": str(e.id), "status": "INDEXED"}

@router.put("/entries/{entry_id}")
async def update(entry_id: uuid.UUID, body: EntryUpdate, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    e = await s.get(FaqEntry, entry_id)
    if not e:
        raise HTTPException(404, "FAQ 条目不存在")
    if body.question is not None:
        e.question = body.question
    if body.answer is not None:
        e.answer = body.answer
    if body.keywords is not None:
        e.keywords = body.keywords
    if body.directory_id is not None:
        e.directory_id = body.directory_id
    await s.commit()
    kb = await s.get(KnowledgeBase, e.kb_id)
    e.status = "DRAFT"; await s.commit()
    try:
        await faq_index.index_entry(kb, e)
        e.status = "INDEXED"
    except Exception:
        e.status = "FAILED"
    await s.commit()
    return {"id": str(e.id), "status": e.status}

@router.get("/knowledge-bases/{kb_id}/entries")
async def list_(kb_id: uuid.UUID, keyword: str = "", status: str | None = None,
                page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """PageResult shape: {items, total, page, size} - aligns with frontend listFaqEntries."""
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    if keyword:
        q = q.where(FaqEntry.question.ilike(f"%{keyword}%"))
    if status:
        q = q.where(FaqEntry.status == status)
    total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await s.execute(q.order_by(FaqEntry.created_at.desc())
                            .offset((page - 1) * size).limit(size))).scalars().all()
    items = [{"id": str(r.id), "kb_id": str(r.kb_id),
              "directory_id": str(r.directory_id) if r.directory_id else None,
              "question": r.question, "answer": r.answer,
              "keywords": r.keywords, "status": r.status,
              "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}

@router.delete("/entries/{entry_id}")
async def delete(entry_id: uuid.UUID, u=Depends(require_role("super_admin", "admin")),
                 s: AsyncSession = Depends(get_session)):
    e = await s.get(FaqEntry, entry_id)
    if e:
        await faq_index.delete_entry(str(e.kb_id), str(e.id))
        await s.delete(e); await s.commit()
    return {"ok": True}

@router.post("/knowledge-bases/{kb_id}/entries/batch")
async def batch(kb_id: uuid.UUID, file: UploadFile = File(...), u=Depends(get_current_user),
                s: AsyncSession = Depends(get_session)):
    rows = await faq_import.parse(file)   # [{question, answer, keywords[]}]
    kb = await s.get(KnowledgeBase, kb_id)
    cnt = 0
    for r in rows:
        e = FaqEntry(kb_id=kb_id, question=r["question"], answer=r["answer"],
                     keywords=r.get("keywords", []), status="DRAFT")
        s.add(e); await s.commit(); await s.refresh(e)
        try: await faq_index.index_entry(kb, e); e.status = "INDEXED"
        except Exception: e.status = "FAILED"
        await s.commit(); cnt += 1
    return {"imported": cnt}
