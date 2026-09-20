from urllib.parse import quote
import base64
from kb_common.config import get_settings
from kb_common.clients import minio_client
from datetime import timedelta


def trace(hit: dict, doc_map: dict) -> dict:
    """hit: 检索结果；doc_map: {document_id: (original_filename, storage_path, file_type)}"""
    doc_id = hit.get("document_id")
    fname, path, ftype = doc_map.get(
        doc_id,
        (hit.get("document_title"), hit.get("source_path"), hit.get("file_type")),
    )
    preview_type = "pdf" if ftype == "pdf" else (
        "image" if ftype in ("jpg", "png", "jpeg") else "office"
    )
    try:
        url = minio_client.minio.presigned_get_object(
            minio_client.RAW, path, expires=timedelta(hours=1)
        )
        encoded = base64.b64encode(url.encode()).decode()
        preview_url = f"{get_settings().kkfv_url}/onlinePreview?url={quote(encoded)}"
    except Exception:
        preview_url = None
    return {
        "chunk_id": hit.get("id"),
        "text": hit.get("text"),
        "score": hit.get("score"),
        "score_type": hit.get("score_type"),
        "rerank_score": hit.get("rerank_score"),
        "source_type": hit.get("kb_type") or "DOCUMENT",
        "document_id": doc_id,
        "document_title": fname,
        "page_number": hit.get("page_number"),
        "chunk_index": hit.get("chunk_index"),
        "directory_path": hit.get("directory_path") or "",
        "source_path": path,
        "preview_url": preview_url,
        "preview_type": preview_type,
        "content_hash": hit.get("content_hash"),
        "faq_answer": hit.get("faq_answer"),
    }
