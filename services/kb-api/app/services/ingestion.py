from fastapi import HTTPException
from kb_common.clients import minio_client
from kb_common.models import Document
import uuid, io

ALLOWED = {"pdf", "doc", "docx", "txt", "md", "csv", "xlsx", "xls"}


async def upload_document(s, kb, file, directory_id, enqueue):
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {ext}")
    data = await file.read()
    obj_key = f"{kb.id}/{uuid.uuid4().hex}.{ext}"
    minio_client.minio.put_object(minio_client.RAW, obj_key, io.BytesIO(data), len(data))
    doc = Document(kb_id=kb.id, directory_id=directory_id, filename=obj_key,
                   original_filename=file.filename, file_type=ext, file_size=len(data),
                   storage_path=obj_key, status="PENDING")
    s.add(doc); await s.commit(); await s.refresh(doc)
    enqueue(str(doc.id))  # 提交 Celery 任务（Task 9）；.delay() 同步返回 AsyncResult
    return doc
