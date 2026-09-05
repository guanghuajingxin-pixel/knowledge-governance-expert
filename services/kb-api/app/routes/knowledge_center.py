"""知识中心跨知识库聚合路由"""
import uuid as _uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase, Directory, Document, User
from kb_common.clients import es_client
from app.schemas import DirOut, KcDocumentOut, TrashItemOut, TaskStatsOut
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1/knowledge-center", tags=["knowledge-center"])

# 回收站自动清理天数
TRASH_RETENTION_DAYS = 20


async def _doc_to_kc_dict(r, directory_name: str | None = None) -> dict:
    """将 Document ORM 行转换为知识中心文档字典"""
    return {
        "id": str(r.id) if hasattr(r, 'id') else str(r[0].id) if isinstance(r, tuple) else str(r.id),
    }


@router.get("/directories")
async def get_unified_tree(
    kb_type: str | None = Query(None),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """获取跨知识库的统一目录树"""
    # 查询所有知识库
    kb_q = select(KnowledgeBase).where(KnowledgeBase.kb_type.in_(['DOCUMENT', 'FAQ']))
    if kb_type:
        kb_q = kb_q.where(KnowledgeBase.kb_type == kb_type)
    kbs = (await s.execute(kb_q)).scalars().all()

    result = []
    for kb in kbs:
        # 文档总数（不含已删除）
        doc_count_q = select(func.count(Document.id)).where(
            Document.kb_id == kb.id,
            Document.is_deleted == False,
        )
        total_docs = (await s.execute(doc_count_q)).scalar() or 0

        # 获取该 KB 的所有目录
        dirs_q = select(Directory).where(Directory.kb_id == kb.id).order_by(Directory.sort_order)
        dirs = (await s.execute(dirs_q)).scalars().all()

        # 统计每个目录的文档数
        dir_doc_counts = {}
        if dirs:
            dir_ids = [d.id for d in dirs]
            count_q = (
                select(Document.directory_id, func.count(Document.id))
                .where(
                    Document.directory_id.in_(dir_ids),
                    Document.is_deleted == False,
                )
                .group_by(Document.directory_id)
            )
            for dir_id, cnt in (await s.execute(count_q)).all():
                dir_doc_counts[str(dir_id)] = cnt

        # 构建目录树
        nodes = {}
        for d in dirs:
            nodes[str(d.id)] = {
                "id": str(d.id),
                "kb_id": str(d.kb_id),
                "parent_id": str(d.parent_id) if d.parent_id else None,
                "name": d.name,
                "sort_order": d.sort_order,
                "document_count": dir_doc_counts.get(str(d.id), 0),
                "children": [],
            }

        roots = []
        for d in dirs:
            node = nodes[str(d.id)]
            if d.parent_id and str(d.parent_id) in nodes:
                nodes[str(d.parent_id)]["children"].append(node)
            else:
                roots.append(node)

        result.append({
            "kb_id": str(kb.id),
            "kb_name": kb.name,
            "kb_type": kb.kb_type,
            "document_count": total_docs,
            "children": roots,
        })

    return result


@router.get("/documents")
async def list_documents(
    kb_id: str | None = Query(None),
    directory_id: str | None = Query(None),
    search: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    status: str | None = Query(None),
    kb_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """跨知识库文档列表（不含已删除）"""
    # 子查询：目录名
    dir_name_subq = (
        select(Directory.name)
        .where(Directory.id == Document.directory_id)
        .correlate(Document)
        .scalar_subquery()
        .label("directory_name")
    )

    q = (
        select(
            Document,
            KnowledgeBase.name.label("kb_name"),
            KnowledgeBase.kb_type.label("kb_type"),
            dir_name_subq,
        )
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(Document.is_deleted == False)
    )

    if kb_id:
        q = q.where(Document.kb_id == kb_id)
    if directory_id:
        q = q.where(Document.directory_id == directory_id)
    if kb_type:
        q = q.where(KnowledgeBase.kb_type == kb_type)
    if search:
        pattern = f"%{search}%"
        q = q.where(Document.original_filename.ilike(pattern))
    if date_from:
        q = q.where(Document.created_at >= date_from)
    if date_to:
        q = q.where(Document.created_at <= date_to)
    if status:
        q = q.where(Document.status == status)

    # 排序
    q = q.order_by(Document.created_at.desc())

    # 计数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await s.execute(count_q)).scalar() or 0

    # 分页
    offset = (page - 1) * size
    q = q.offset(offset).limit(size)
    rows = (await s.execute(q)).all()

    items = []
    for row in rows:
        doc = row[0]
        items.append({
            "id": str(doc.id),
            "kb_id": str(doc.kb_id),
            "kb_name": row.kb_name or "",
            "kb_type": row.kb_type or "",
            "directory_id": str(doc.directory_id) if doc.directory_id else None,
            "directory_name": row.directory_name or None,
            "original_filename": doc.original_filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "uploader_name": None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        })

    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/documents/{doc_id}")
async def get_document_detail(
    doc_id: _uuid.UUID,
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """获取文档详情（含知识库信息）"""
    dir_name_subq = (
        select(Directory.name)
        .where(Directory.id == Document.directory_id)
        .correlate(Document)
        .scalar_subquery()
        .label("directory_name")
    )

    q = (
        select(
            Document,
            KnowledgeBase.name.label("kb_name"),
            KnowledgeBase.kb_type.label("kb_type"),
            dir_name_subq,
        )
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(Document.id == doc_id)
    )
    row = (await s.execute(q)).first()
    if not row:
        raise HTTPException(404, "文档不存在")

    doc = row[0]
    return {
        "id": str(doc.id),
        "kb_id": str(doc.kb_id),
        "kb_name": row.kb_name or "",
        "kb_type": row.kb_type or "",
        "directory_id": str(doc.directory_id) if doc.directory_id else None,
        "directory_name": row.directory_name or None,
        "original_filename": doc.original_filename,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "error_message": doc.error_message,
        "storage_path": doc.storage_path,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.get("/recycle-bin")
async def list_recycle_bin(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """回收站列表"""
    dir_name_subq = (
        select(Directory.name)
        .where(Directory.id == Document.directory_id)
        .correlate(Document)
        .scalar_subquery()
        .label("directory_name")
    )

    q = (
        select(
            Document,
            KnowledgeBase.name.label("kb_name"),
            dir_name_subq,
        )
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(Document.is_deleted == True)
        .order_by(Document.deleted_at.desc().nulls_last())
    )

    count_q = select(func.count()).select_from(q.subquery())
    total = (await s.execute(count_q)).scalar() or 0

    offset = (page - 1) * size
    q = q.offset(offset).limit(size)
    rows = (await s.execute(q)).all()

    now = datetime.utcnow()
    items = []
    for row in rows:
        doc = row[0]
        deleted_at = doc.deleted_at
        remaining_days = 0
        if deleted_at:
            expiry = deleted_at + timedelta(days=TRASH_RETENTION_DAYS)
            remaining_days = max(0, (expiry - now).days)

        items.append({
            "id": str(doc.id),
            "original_filename": doc.original_filename,
            "directory_name": row.directory_name or None,
            "kb_name": row.kb_name or "",
            "operator_name": "",
            "deleted_at": deleted_at.isoformat() if deleted_at else None,
            "remaining_days": remaining_days,
        })

    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/recycle-bin/{doc_id}/restore")
async def restore_document(
    doc_id: _uuid.UUID,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """从回收站恢复文档"""
    doc = await s.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    doc.is_deleted = False
    doc.deleted_at = None
    await s.commit()
    return {"ok": True}


@router.delete("/recycle-bin/{doc_id}")
async def permanent_delete_document(
    doc_id: _uuid.UUID,
    u=Depends(require_role("super_admin", "admin")),
    s: AsyncSession = Depends(get_session),
):
    """永久删除文档（ES + DB）"""
    doc = await s.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")

    # 删除 ES 索引
    kb = await s.get(KnowledgeBase, doc.kb_id)
    if kb:
        try:
            from kb_common.rag.indexer import indexer
            await es_client.es.delete(index=kb.es_index_name, id=str(doc_id), ignore=[404])
        except Exception:
            pass

    await s.delete(doc)
    await s.commit()
    return {"ok": True}


@router.get("/task-stats")
async def get_task_stats(
    kb_type: str | None = Query(None),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """任务队列统计"""
    q = select(
        func.count(Document.id).label("total"),
        func.count(case((Document.status.in_(
            ["PENDING", "PARSING", "CHUNKING", "EMBEDDING", "INDEXING"]
        ), Document.id))).label("executing"),
        func.count(case((Document.status == "COMPLETED", Document.id))).label("completed"),
        func.count(case((Document.status == "FAILED", Document.id))).label("failed"),
    ).where(Document.is_deleted == False)

    if kb_type:
        q = q.join(KnowledgeBase, Document.kb_id == KnowledgeBase.id).where(
            KnowledgeBase.kb_type == kb_type
        )

    row = (await s.execute(q)).first()
    return {
        "total": row.total or 0,
        "executing": row.executing or 0,
        "completed": row.completed or 0,
        "failed": row.failed or 0,
    }
