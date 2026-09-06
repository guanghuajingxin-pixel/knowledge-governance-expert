"""知识中心跨知识库聚合路由"""
import asyncio
import json
import logging
import os
import time
import uuid as _uuid
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase, Directory, Document, User
from kb_common.clients import es_client
from app.schemas import DirOut, KcDocumentOut, TrashItemOut, TaskStatsOut
from app.deps import get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge-center", tags=["knowledge-center"])

# 回收站自动清理天数
TRASH_RETENTION_DAYS = 20

# 钉钉知识库文件列表内存缓存（全量遍历数千节点耗时较长，后台异步刷新）
# loading=True 表示后台遍历进行中；files 已有时为旧数据（stale-while-revalidate）
_dingtalk_cache: dict = {"files": None, "expire_at": 0.0, "loading": False, "error": None}
_DINGTALK_TTL = 3600  # 1 小时；「手动刷新」强制重新拉取

# 钉钉全量遍历结果磁盘快照：进程重启/uvicorn --reload 后用快照快速预热，
# 避免每次冷启动都等待数十分钟的全量遍历（可用 KGE_DINGTALK_SNAPSHOT 覆盖路径）。
_SNAPSHOT_PATH = Path(os.getenv("KGE_DINGTALK_SNAPSHOT", "/tmp/kge_dingtalk_files.json"))
_snapshot_loaded = False


def _load_dingtalk_snapshot() -> None:
    """进程冷启动后用磁盘快照预热内存缓存。

    快照文件尚不存在时（首次遍历未落盘）保持未加载状态，后续请求继续尝试，
    使晚于进程启动落盘的快照也能被发现。
    """
    global _snapshot_loaded
    if _snapshot_loaded:
        return
    try:
        if not _SNAPSHOT_PATH.exists():
            return
        _snapshot_loaded = True
        data = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        fetched_at = float(data.get("fetched_at") or 0)
        files = data.get("files")
        if files:
            # 即使快照已过期也加载（有数据总比空等好），同时置 expire_at=now 触发后台刷新
            _dingtalk_cache["files"] = files
            _dingtalk_cache["expire_at"] = fetched_at + _DINGTALK_TTL
            logger.info("钉钉文件快照预热完成：%d 个文件", len(files))
    except Exception as e:
        logger.warning("钉钉文件快照加载失败：%s", e)


def _save_dingtalk_snapshot(files: list) -> None:
    """全量遍历成功后落盘快照（原子替换），供下次进程启动预热。"""
    try:
        tmp_path = _SNAPSHOT_PATH.with_name(_SNAPSHOT_PATH.name + ".tmp")
        tmp_path.write_text(
            json.dumps({"fetched_at": time.time(), "files": files}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(_SNAPSHOT_PATH)
    except Exception as e:
        logger.warning("钉钉文件快照写入失败：%s", e)


async def _refresh_dingtalk_files() -> None:
    """后台任务：遍历全部钉钉知识库并写缓存 + 落盘快照。"""
    from kb_common.clients import dingtalk_client
    try:
        await dingtalk_client.sync_runtime_config()
        files = await dingtalk_client.get_all_knowledge_files()
        _dingtalk_cache["files"] = files
        _dingtalk_cache["expire_at"] = time.time() + _DINGTALK_TTL
        _dingtalk_cache["error"] = None
        _save_dingtalk_snapshot(files)
    except Exception as e:
        _dingtalk_cache["error"] = f"钉钉数据拉取失败：{e}"
    finally:
        _dingtalk_cache["loading"] = False


def _trigger_dingtalk_refresh(force: bool = False) -> None:
    """缓存缺失/过期时启动后台遍历（单飞：正在遍历则跳过）。"""
    _load_dingtalk_snapshot()
    now = time.time()
    fresh = (not force) and _dingtalk_cache["files"] and _dingtalk_cache["expire_at"] > now
    if fresh or _dingtalk_cache["loading"]:
        return
    _dingtalk_cache["loading"] = True
    asyncio.create_task(_refresh_dingtalk_files())


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
    uploader_id: str | None = Query(None),
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

    uploader_name_subq = (
        select(User.username)
        .where(User.id == Document.uploader_id)
        .correlate(Document)
        .scalar_subquery()
        .label("uploader_name")
    )

    q = (
        select(
            Document,
            KnowledgeBase.name.label("kb_name"),
            KnowledgeBase.kb_type.label("kb_type"),
            dir_name_subq,
            uploader_name_subq,
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
    if uploader_id:
        ids = [uid.strip() for uid in uploader_id.split(",") if uid.strip()]
        if ids:
            q = q.where(Document.uploader_id.in_(ids))

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
            "uploader_id": str(doc.uploader_id) if doc.uploader_id else None,
            "uploader_name": row.uploader_name or None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        })

    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/uploaders")
async def list_uploaders(
    kb_type: str | None = Query(None),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """获取有文档的创建人列表（用于筛选下拉）"""
    q = (
        select(User.id, User.username)
        .join(Document, Document.uploader_id == User.id)
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(Document.is_deleted == False)
        .distinct()
    )
    if kb_type:
        q = q.where(KnowledgeBase.kb_type == kb_type)
    rows = (await s.execute(q)).all()
    return [{"id": str(r.id), "name": r.username} for r in rows]


@router.get("/dingtalk/documents")
async def list_dingtalk_documents(
    workspace_id: str | None = Query(None, description="知识库ID，逗号分隔多选"),
    creator_id: str | None = Query(None, description="创建人userid，逗号分隔多选"),
    search: str | None = Query(None, description="按文件名模糊匹配"),
    directory: str | None = Query(None, description="按目录路径模糊匹配"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    refresh: bool = Query(False, description="为 true 时绕过缓存重新拉取钉钉"),
    u=Depends(get_current_user),
):
    """钉钉知识库文件列表（实时拉取钉钉开放平台数据）。

    全量遍历操作人可见的团队知识库（耗时较长）改为后台任务执行，本接口立即返回：
    首次/过期时返回 loading=true（前端轮询），缓存命中时直接返回数据；
    「手动刷新」(refresh=true) 触发后台重新遍历，期间继续返回旧数据。
    文件含多层目录路径（/ 分隔），创建人 userid 经钉钉通讯录接口解析为姓名。
    """
    from kb_common.clients import dingtalk_client

    config_error = None
    try:
        await dingtalk_client.sync_runtime_config()
        if not dingtalk_client.is_configured():
            config_error = "钉钉 AppKey/AppSecret/操作人 未配置，请在「系统配置」中填写后重试"
    except Exception as e:
        config_error = f"钉钉配置加载失败：{e}"

    if config_error:
        return {
            "items": [], "total": 0, "page": page, "size": size,
            "workspaces": [], "creators": [],
            "loading": False, "error": config_error,
        }

    _trigger_dingtalk_refresh(force=refresh)
    loading = _dingtalk_cache["loading"] and not _dingtalk_cache["files"]
    cached_files = _dingtalk_cache["files"]

    # 首次同步尚未完成：不挂起请求，返回 loading 让前端轮询
    if not cached_files:
        return {
            "items": [], "total": 0, "page": page, "size": size,
            "workspaces": [], "creators": [],
            "loading": True, "error": _dingtalk_cache["error"],
        }

    files = list(cached_files)
    # 知识库 / 创建人过滤选项（从文件数据聚合，避免额外接口调用）
    workspace_map: dict[str, str] = {}
    creator_ids: set[str] = set()
    for f in files:
        if f.get("workspace_id") and f.get("workspace_name"):
            workspace_map[f["workspace_id"]] = f["workspace_name"]
        if f.get("creator_id"):
            creator_ids.add(f["creator_id"])

    name_map = await dingtalk_client.get_user_name_map(list(creator_ids))
    creators = [
        {"id": uid, "name": name_map.get(uid) or uid}
        for uid in sorted(creator_ids, key=lambda x: name_map.get(x, ""))
    ]
    workspaces = [{"id": wid, "name": name} for wid, name in workspace_map.items()]

    # 过滤
    ws_ids = {v.strip() for v in workspace_id.split(",") if v.strip()} if workspace_id else set()
    cr_ids = {v.strip() for v in creator_id.split(",") if v.strip()} if creator_id else set()
    if ws_ids:
        files = [f for f in files if f.get("workspace_id") in ws_ids]
    if cr_ids:
        files = [f for f in files if f.get("creator_id") in cr_ids]
    if search:
        kw = search.strip().lower()
        files = [f for f in files if kw in (f.get("name") or "").lower()]
    if directory:
        kw = directory.strip()
        files = [f for f in files if kw in (f.get("directory_path") or "")]

    # 按创建时间倒序
    files.sort(key=lambda f: f.get("created_at") or "", reverse=True)

    total = len(files)
    start = (page - 1) * size
    page_items = files[start:start + size]
    items = []
    for f in page_items:
        items.append({
            "node_id": f.get("node_id"),
            "workspace_id": f.get("workspace_id"),
            "workspace_name": f.get("workspace_name") or "",
            "name": f.get("name") or "",
            "directory_path": f.get("directory_path") or "/",
            "category": f.get("category"),
            "extension": f.get("extension"),
            "size": f.get("size") or 0,
            "url": f.get("url"),
            "creator_id": f.get("creator_id") or "",
            "creator_name": name_map.get(f.get("creator_id") or "", "") or None,
            "created_at": f.get("created_at"),
            "modified_at": f.get("modified_at"),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "workspaces": workspaces,
        "creators": creators,
        "loading": _dingtalk_cache["loading"],
        "error": _dingtalk_cache["error"],
    }


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
