from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase, User, Document
from kb_common.clients import es_client
from app.schemas import KbIn, KbOut
from app.deps import get_current_user, require_role
import uuid as _uuid

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["kb"])


@router.post("", response_model=KbOut)
async def create_kb(body: KbIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    # 预生成 kb_id，使 es_index_name 与 ensure_index 创建的索引名一致
    # (ensure_index 内部用 f"kb_{kb_id.replace('-','')}" 作为索引名)
    kb_id = _uuid.uuid4()
    kb = KnowledgeBase(id=kb_id, **body.model_dump(), owner_id=u.id,
                       es_index_name=f"kb_{kb_id.hex}")
    s.add(kb); await s.commit(); await s.refresh(kb)
    await es_client.ensure_index(str(kb_id))
    return kb


@router.get("")
async def list_kb(
    kb_type: str | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    # 文档数量子查询
    doc_count_subq = (
        select(func.count(Document.id))
        .where(Document.kb_id == KnowledgeBase.id)
        .correlate(KnowledgeBase)
        .scalar_subquery()
        .label("document_count")
    )

    q = select(
        KnowledgeBase,
        User.username.label("owner_name"),
        doc_count_subq,
    ).join(User, KnowledgeBase.owner_id == User.id)

    if kb_type:
        q = q.where(KnowledgeBase.kb_type == kb_type)

    if search:
        pattern = f"%{search}%"
        q = q.where(
            KnowledgeBase.name.ilike(pattern)
            | KnowledgeBase.description.ilike(pattern)
        )

    # 排序
    allowed_sort = {"created_at", "name", "kb_type"}
    col = sort_by if sort_by in allowed_sort else "created_at"
    sort_col = getattr(KnowledgeBase, col)
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    # 计数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await s.execute(count_q)).scalar() or 0

    # 分页
    offset = (page - 1) * size
    q = q.offset(offset).limit(size)

    rows = (await s.execute(q)).all()

    items = []
    for kb, owner_name, doc_count in rows:
        items.append({
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description or "",
            "kb_type": kb.kb_type,
            "owner_id": str(kb.owner_id),
            "owner_name": owner_name or "",
            "chunk_strategy": kb.chunk_strategy,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "delimiter": kb.delimiter,
            "embedding_model": kb.embedding_model,
            "es_index_name": kb.es_index_name,
            "document_count": doc_count or 0,
            "status": "正常",
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
            "updated_at": kb.created_at.isoformat() if kb.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/{kb_id}", response_model=KbOut)
async def get_kb(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.delete("/{kb_id}")
async def delete_kb(kb_id: _uuid.UUID, u=Depends(require_role("super_admin", "admin")),
                    s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if kb:
        if await es_client.es.indices.exists(index=kb.es_index_name):
            await es_client.es.indices.delete(index=kb.es_index_name)
        await s.delete(kb); await s.commit()
    return {"ok": True}
