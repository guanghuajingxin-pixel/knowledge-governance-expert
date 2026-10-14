"""业务系统知识推送接口（AK/SK + HMAC 请求签名鉴权，无用户 JWT）。

POST /api/v1/ingest/{library_id}/documents
- multipart：file（必填）+ title（可选，覆盖展示名，仍须带合法扩展名）
- 鉴权：X-AK-Id / X-Timestamp / X-Nonce / X-Signature 四头（见 services/business_auth.py）
- 授权：目标文档库必须在凭证的可推送白名单内
- 入库：复用文档库公共链路（MinIO + LibraryDocument + MinerU 解析），source='business'
"""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import BusinessCredential, KnowledgeSource
from app.services.business_auth import verify_business_signature
from app.routes.managed_library import (
    _MAX_UPLOAD_BYTES, _validated_upload_name, doc_out, ingest_file, library,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ingest", tags=["business-ingest"])


@router.post("/{library_id}/documents")
async def ingest_document(library_id: int,
                          file: UploadFile = File(...),
                          title: str = Form(default=""),
                          cred: BusinessCredential = Depends(verify_business_signature),
                          s: AsyncSession = Depends(get_session)):
    """业务系统推送文档：签名验证（依赖）→ 库授权校验 → 入库并自动解析。"""
    if library_id not in (cred.library_ids or []):
        raise HTTPException(403, "该凭证未被授权推送至此文档库")
    # 目标库有效性（存在且为文档库）
    await library(s, library_id)

    name = _validated_upload_name(title.strip() or file.filename)
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "请推送非空且不超过 64 MB 的文件")

    source = await s.get(KnowledgeSource, cred.source_id)
    doc = await ingest_file(s, library_id, name, content,
                            source="business",
                            updated_by=f"业务系统:{source.name if source else cred.source_id}")
    logger.info("business ingest: ak=%s library=%s doc=%s name=%s",
                cred.access_key_id, library_id, doc.id, name)
    return doc_out(doc)
