from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Document, Segment, KnowledgeBase
from kb_common.clients import es_client, minio_client
from kb_common.config import get_settings
from app.services.ingestion import upload_document
from app.deps import get_current_user
from app.worker import process_document
import uuid, urllib.parse, base64

router = APIRouter(prefix="/api/v1", tags=["doc"])


@router.post("/documents/upload")
async def upload(kb_id: uuid.UUID = Query(...), directory_id: uuid.UUID | None = Query(None),
                 file: UploadFile = File(...), u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id) or (_ for _ in ()).throw(HTTPException(404))
    doc = await upload_document(s, kb, file, directory_id, lambda did: process_document.delay(did))
    return {"document_id": str(doc.id), "status": doc.status}


@router.get("/documents")
async def list_docs(kb_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "filename": r.original_filename, "file_type": r.file_type,
             "file_size": r.file_size, "status": r.status, "chunk_count": r.chunk_count,
             "error_message": r.error_message} for r in rows]


@router.get("/documents/{doc_id}/segments")
async def segments(doc_id: uuid.UUID, page: int = 1, size: int = 20,
                   u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    q = select(Segment).where(Segment.document_id == doc_id).order_by(Segment.chunk_index)\
        .offset((page - 1) * size).limit(size)
    rows = (await s.execute(q)).scalars().all()
    return [{"chunk_index": r.chunk_index, "content": r.content, "content_hash": r.content_hash,
             "token_count": r.token_count, "page_number": r.page_number} for r in rows]


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
async def del_doc(doc_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Document, doc_id)
    if d:
        kb = await s.get(KnowledgeBase, d.kb_id)
        await es_client.delete_by_doc(kb.es_index_name, str(d.id))
        await s.delete(d); await s.commit()
    return {"ok": True}


@router.post("/documents/{doc_id}/reprocess")
async def reprocess(doc_id: uuid.UUID, u=Depends(get_current_user)):
    process_document.delay(str(doc_id))
    return {"ok": True}
