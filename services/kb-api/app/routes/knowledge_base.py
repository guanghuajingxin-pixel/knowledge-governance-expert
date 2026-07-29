from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase
from kb_common.clients import es_client
from app.schemas import KbIn, KbOut
from app.deps import get_current_user
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
async def list_kb(kb_type: str | None = Query(None),
                  u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    q = select(KnowledgeBase)
    if kb_type:
        q = q.where(KnowledgeBase.kb_type == kb_type)
    rows = (await s.execute(q.order_by(KnowledgeBase.created_at.desc()))).scalars().all()
    items = [{"id": str(r.id), "name": r.name, "description": r.description,
              "kb_type": r.kb_type, "owner_id": str(r.owner_id),
              "chunk_strategy": r.chunk_strategy, "chunk_size": r.chunk_size,
              "chunk_overlap": r.chunk_overlap, "embedding_model": r.embedding_model,
              "es_index_name": r.es_index_name,
              "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return {"items": items, "total": len(items), "page": 1, "size": len(items)}


@router.get("/{kb_id}", response_model=KbOut)
async def get_kb(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.delete("/{kb_id}")
async def delete_kb(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if kb:
        if await es_client.es.indices.exists(index=kb.es_index_name):
            await es_client.es.indices.delete(index=kb.es_index_name)
        await s.delete(kb); await s.commit()
    return {"ok": True}
