from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import FaqEntry, KnowledgeBase
from app.deps import get_current_user
from app.services import faq_index, faq_import
import uuid
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/faq", tags=["faq-entry"])


def _item(r: FaqEntry) -> dict:
    return {
        "id": str(r.id), "kb_id": str(r.kb_id),
        "directory_id": str(r.directory_id) if r.directory_id else None,
        "question": r.question, "answer": r.answer,
        "keywords": r.keywords or [], "similar_questions": r.similar_questions or [],
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


class EntryIn(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    keywords: list[str] = []
    similar_questions: list[str] = []
    directory_id: uuid.UUID | None = None


class EntryUpdate(BaseModel):
    """部分更新：仅提供的字段会被写入（传空数组可清空列表字段）。"""
    question: str | None = None
    answer: str | None = None
    keywords: list[str] | None = None
    similar_questions: list[str] | None = None
    directory_id: uuid.UUID | None = None


@router.post("/knowledge-bases/{kb_id}/entries")
async def create(kb_id: uuid.UUID, body: EntryIn, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "问答库不存在")
    e = FaqEntry(kb_id=kb_id, directory_id=body.directory_id, question=body.question,
                 answer=body.answer, keywords=body.keywords,
                 similar_questions=body.similar_questions, status="DRAFT")
    s.add(e); await s.commit(); await s.refresh(e)
    try:
        await faq_index.index_entry(kb, e)
        e.status = "INDEXED"
    except Exception:
        e.status = "FAILED"
    await s.commit(); await s.refresh(e)
    return _item(e)


@router.put("/entries/{entry_id}")
async def update(entry_id: uuid.UUID, body: EntryUpdate, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    e = await s.get(FaqEntry, entry_id)
    if not e:
        raise HTTPException(404, "FAQ 条目不存在")
    for field in ("question", "answer", "keywords", "similar_questions", "directory_id"):
        if getattr(body, field) is not None:
            setattr(e, field, getattr(body, field))
    kb = await s.get(KnowledgeBase, e.kb_id)
    e.status = "DRAFT"; await s.commit(); await s.refresh(e)
    try:
        await faq_index.index_entry(kb, e)
        e.status = "INDEXED"
    except Exception:
        e.status = "FAILED"
    await s.commit(); await s.refresh(e)
    return _item(e)


@router.get("/knowledge-bases/{kb_id}/entries")
async def list_(kb_id: uuid.UUID, keyword: str = "", status: str | None = None,
                page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """PageResult shape: {items, total, page, size} - aligns with frontend listFaqEntries.

    keyword 同时检索问题、答案与相似问（相似问命中仍是同一条问答数据）。
    """
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    if keyword:
        pattern = f"%{keyword}%"
        q = q.where(or_(
            FaqEntry.question.ilike(pattern),
            FaqEntry.answer.ilike(pattern),
            func.array_to_string(FaqEntry.similar_questions, ' || ').ilike(pattern),
        ))
    if status:
        q = q.where(FaqEntry.status == status)
    total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await s.execute(q.order_by(FaqEntry.created_at.desc())
                            .offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [_item(r) for r in rows], "total": total, "page": page, "size": size}


@router.delete("/entries/{entry_id}")
async def delete(entry_id: uuid.UUID, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    e = await s.get(FaqEntry, entry_id)
    if e:
        await faq_index.delete_entry(str(e.kb_id), str(e.id))
        await s.delete(e); await s.commit()
    return {"ok": True}


@router.post("/knowledge-bases/{kb_id}/entries/batch")
async def batch(kb_id: uuid.UUID, file: UploadFile = File(...), u=Depends(get_current_user),
                s: AsyncSession = Depends(get_session)):
    """批量导入：模板列「问题/相似问/答案/关键词」。

    - 相似问单元格内用分号或换行分隔多个问句
    - 同一问题拆分多行（问题与答案相同）自动合并为一条问答
    - imported = 成功入库条数；failed = 解析无效（缺问题或答案）行数；
      index_failed = 入库成功但向量索引失败条数（外部向量服务恢复后可重新编辑触发重建）
    """
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "问答库不存在")
    try:
        rows, skipped = await faq_import.parse(file)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    imported = 0
    failed = skipped
    index_failed = 0
    for r in rows:
        e = FaqEntry(kb_id=kb_id, question=r["question"], answer=r["answer"],
                     keywords=r.get("keywords", []),
                     similar_questions=r.get("similar_questions", []), status="DRAFT")
        s.add(e); await s.commit(); await s.refresh(e)
        try:
            await faq_index.index_entry(kb, e)
            e.status = "INDEXED"
        except Exception:
            e.status = "FAILED"; index_failed += 1
        await s.commit()
        imported += 1
    return {"imported": imported, "failed": failed, "index_failed": index_failed}
