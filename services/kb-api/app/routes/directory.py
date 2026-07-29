from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Directory
from app.schemas import DirIn
from app.deps import get_current_user
import uuid

router = APIRouter(prefix="/api/v1", tags=["dir"])


@router.post("/knowledge-bases/{kb_id}/directories")
async def create_dir(kb_id: uuid.UUID, body: DirIn, u=Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    d = Directory(kb_id=kb_id, parent_id=body.parent_id, name=body.name)
    s.add(d); await s.commit(); await s.refresh(d)
    return {"id": str(d.id)}


@router.get("/knowledge-bases/{kb_id}/directories")
async def tree(kb_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    """Return nested tree (parent -> children) for el-tree.
    Frontend DirectoryTree.vue uses :props="{label:'name', children:'children'}"
    and expects top-level nodes (parent_id=null) with nested `children`."""
    rows = (await s.execute(select(Directory).where(Directory.kb_id == kb_id)
                            .order_by(Directory.sort_order, Directory.created_at))).scalars().all()
    nodes: dict[str, dict] = {}
    for r in rows:
        nodes[str(r.id)] = {"id": str(r.id), "kb_id": str(r.kb_id),
                            "parent_id": str(r.parent_id) if r.parent_id else None,
                            "name": r.name, "sort_order": r.sort_order,
                            "created_at": r.created_at.isoformat() if r.created_at else None,
                            "children": []}
    roots: list[dict] = []
    for r in rows:
        nid, pid = str(r.id), (str(r.parent_id) if r.parent_id else None)
        if pid and pid in nodes:
            nodes[pid]["children"].append(nodes[nid])
        else:
            roots.append(nodes[nid])
    return roots


@router.delete("/directories/{dir_id}")
async def del_dir(dir_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Directory, dir_id)
    if d:
        await s.delete(d); await s.commit()
    return {"ok": True}
