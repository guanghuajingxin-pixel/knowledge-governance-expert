"""FAQ 目录 CRUD - 同 Task 5 directory.py，但操作 FaqDirectory，路径前缀 /api/v1/faq。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import FaqDirectory
from app.deps import get_current_user, require_role
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq", tags=["faq-dir"])


class DirIn(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


@router.post("/knowledge-bases/{kb_id}/directories")
async def create_dir(kb_id: uuid.UUID, body: DirIn, u=Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    d = FaqDirectory(kb_id=kb_id, parent_id=body.parent_id, name=body.name)
    s.add(d); await s.commit(); await s.refresh(d)
    return {"id": str(d.id)}


@router.get("/knowledge-bases/{kb_id}/directories")
async def tree(kb_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(FaqDirectory).where(FaqDirectory.kb_id == kb_id))).scalars().all()
    return [{"id": str(r.id), "parent_id": str(r.parent_id) if r.parent_id else None,
             "name": r.name, "sort_order": r.sort_order} for r in rows]


@router.delete("/directories/{dir_id}")
async def del_dir(dir_id: uuid.UUID, u=Depends(require_role("super_admin", "admin")),
                  s: AsyncSession = Depends(get_session)):
    d = await s.get(FaqDirectory, dir_id)
    if d:
        await s.delete(d); await s.commit()
    return {"ok": True}
