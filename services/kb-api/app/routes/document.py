from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Document, Segment, KnowledgeBase
from kb_common.clients import es_client, minio_client
from kb_common.config import get_settings
from app.services.ingestion import upload_document
from app.deps import get_current_user, require_role
from app.worker import process_document
import uuid, urllib.parse, base64


def _doc_dict(r: Document) -> dict:
    return {"id": str(r.id), "kb_id": str(r.kb_id),
            "directory_id": str(r.directory_id) if r.directory_id else None,
            "filename": r.filename, "original_filename": r.original_filename,
            "file_type": r.file_type, "file_size": r.file_size, "storage_path": r.storage_path,
            "status": r.status, "chunk_count": r.chunk_count, "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}

router = APIRouter(prefix="/api/v1", tags=["doc"])


@router.post("/documents/upload")
async def upload(kb_id: uuid.UUID = Query(...), directory_id: uuid.UUID | None = Query(None),
                 file: UploadFile = File(...), u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id) or (_ for _ in ()).throw(HTTPException(404))
    doc = await upload_document(s, kb, file, directory_id, lambda did: process_document.delay(did))
    return {"document_id": str(doc.id), "status": doc.status}


@router.get("/documents")
async def list_docs(kb_id: uuid.UUID = Query(...),
                    directory_id: uuid.UUID | None = Query(None),
                    page: int = Query(1, ge=1), size: int = Query(10, ge=1),
                    u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    q = select(Document).where(Document.kb_id == kb_id, Document.is_deleted == False)
    if directory_id:
        q = q.where(Document.directory_id == directory_id)
    total = (await s.execute(
        select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await s.execute(q.order_by(Document.created_at.desc())
                            .offset((page - 1) * size).limit(size))).scalars().all()
    items = [_doc_dict(r) for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/documents/{doc_id}")
async def get_doc(doc_id: uuid.UUID, u=Depends(get_current_user),
                  s: AsyncSession = Depends(get_session)):
    r = await s.get(Document, doc_id) or (_ for _ in ()).throw(HTTPException(404))
    return _doc_dict(r)


@router.get("/documents/{doc_id}/segments")
async def segments(doc_id: uuid.UUID, page: int = Query(1, ge=1), size: int = Query(20, ge=1),
                   u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    base_q = select(Segment).where(Segment.document_id == doc_id)
    total = (await s.execute(
        select(func.count()).select_from(base_q.subquery()))).scalar_one()
    rows = (await s.execute(base_q.order_by(Segment.chunk_index)
                            .offset((page - 1) * size).limit(size))).scalars().all()
    items = [{"id": str(r.id), "document_id": str(r.document_id) if r.document_id else None,
              "es_chunk_id": r.es_chunk_id, "chunk_index": r.chunk_index, "content": r.content,
              "content_hash": r.content_hash, "token_count": r.token_count,
              "page_number": r.page_number,
              "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/documents/{doc_id}/preview")
async def preview(doc_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Document, doc_id) or (_ for _ in ()).throw(HTTPException(404))
    kb = await s.get(KnowledgeBase, d.kb_id)
    # MinIO 生成临时下载 URL，base64 编码给 kkFileView
    from datetime import timedelta
    url = minio_client.minio.presigned_get_object(minio_client.RAW, d.storage_path, expires=timedelta(hours=1))
    encoded = base64.b64encode(url.encode()).decode()
    return {"preview_url": f"{get_settings().kkfv_url}/onlinePreview?url={urllib.parse.quote(encoded)}",
            "preview_type": "pdf" if d.file_type == "pdf" else "office"}


@router.delete("/documents/{doc_id}")
async def del_doc(doc_id: uuid.UUID, u=Depends(require_role("super_admin", "admin")),
                  s: AsyncSession = Depends(get_session)):
    """软删除文档（移入回收站，20天后自动清理）"""
    d = await s.get(Document, doc_id)
    if d:
        from datetime import datetime as _dt
        d.is_deleted = True
        d.deleted_at = _dt.utcnow()
        await s.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/reprocess")
async def reprocess(doc_id: uuid.UUID, u=Depends(require_role("super_admin", "admin"))):
    process_document.delay(str(doc_id))
    return {"ok": True}
