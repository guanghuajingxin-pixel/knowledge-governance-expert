from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import FaqEntry, KnowledgeBase
from app.deps import get_current_user
from app.services import faq_index, faq_import
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq", tags=["faq-entry"])

class EntryIn(BaseModel):
    question: str
    answer: str
    keywords: list[str] = []
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

@router.get("/knowledge-bases/{kb_id}/entries")
async def list_(kb_id: uuid.UUID, keyword: str = "", u=Depends(get_current_user),
                s: AsyncSession = Depends(get_session)):
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    if keyword:
        q = q.where(FaqEntry.question.ilike(f"%{keyword}%"))
    rows = (await s.execute(q.order_by(FaqEntry.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "question": r.question, "answer": r.answer,
             "keywords": r.keywords, "status": r.status} for r in rows]

@router.delete("/entries/{entry_id}")
async def delete(entry_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
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
