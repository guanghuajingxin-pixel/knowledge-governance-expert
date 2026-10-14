from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase, FaqEntry
from kb_common.clients import es_client
from app.deps import get_current_user
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq/knowledge-bases", tags=["faq-kb"])

class KbIn(BaseModel):
    name: str
    description: str | None = None

@router.post("")
async def create_kb(body: KbIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    # 预生成 kb_id，使 es_index_name 与 ensure_index 实际创建的索引名一致
    # （ensure_index 内部用 f"kb_{kb_id.replace('-','')}"，即 uuid 去连字符）
    kb_id = uuid.uuid4()
    kb = KnowledgeBase(id=kb_id, name=body.name, description=body.description, kb_type="FAQ",
                       owner_id=u.id, es_index_name=f"kb_{kb_id.hex}",
                       chunk_strategy="FIXED_SIZE")
    s.add(kb); await s.commit(); await s.refresh(kb)
    await es_client.ensure_index(str(kb.id))
    return {"id": str(kb.id), "name": kb.name}


@router.put("/{kb_id}")
async def update_kb(kb_id: uuid.UUID, body: KbIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """编辑 FAQ 问答库基础信息（名称/描述），仅作用于 kb_type=FAQ 的库。"""
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb or kb.kb_type != "FAQ":
        raise HTTPException(404, "问答库不存在")
    kb.name = body.name
    kb.description = body.description
    await s.commit()
    return {"id": str(kb.id), "name": kb.name, "description": kb.description}


@router.get("")
async def list_kb(u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    # 问答数子查询：FAQ 库列表展示实际条目数
    entry_count_subq = (
        select(func.count(FaqEntry.id))
        .where(FaqEntry.kb_id == KnowledgeBase.id)
        .correlate(KnowledgeBase)
        .scalar_subquery()
    )
    q = (select(KnowledgeBase, entry_count_subq)
         .where(KnowledgeBase.kb_type == "FAQ")
         .order_by(KnowledgeBase.created_at.desc()))
    rows = (await s.execute(q)).all()
    return [{"id": str(kb.id), "name": kb.name, "description": kb.description,
             "entry_count": count or 0,
             "created_at": kb.created_at.isoformat() if kb.created_at else None}
            for kb, count in rows]
