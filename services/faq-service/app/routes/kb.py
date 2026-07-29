from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase
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
    kb = KnowledgeBase(name=body.name, description=body.description, kb_type="FAQ",
                       owner_id=u.id, es_index_name=f"kb_{uuid.uuid4().hex}",
                       chunk_strategy="FIXED_SIZE")
    s.add(kb); await s.commit(); await s.refresh(kb)
    await es_client.ensure_index(str(kb.id))
    return {"id": str(kb.id), "name": kb.name}

@router.get("")
async def list_kb(u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(KnowledgeBase).where(KnowledgeBase.kb_type == "FAQ"))).scalars().all()
    return [{"id": str(r.id), "name": r.name, "description": r.description} for r in rows]
