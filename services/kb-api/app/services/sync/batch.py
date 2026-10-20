"""library 同步批处理：XXL-Job 全局作业每轮消费一批待处理任务（默认 30s × 5 篇）。

每轮四段：
(a) 自愈：回收卡死 running 的批处理任务（kb-api 崩溃/被 kill 后悬挂回退 pending；
    关联文档仍在 PARSING 解析中的不回收，等 (c) 收尾）；
(b) 认领：FOR UPDATE SKIP LOCKED 取最早 N 个 pending 任务（跨源全局 FIFO），
    必须先于 refresh：refresh 受外部服务延迟影响可能耗时数分钟，排在前面会
    饿死认领（新任务迟迟不流转 running，run 被看门狗收编）；
(c) refresh：跟进 PARSING 中的同步文档（查 MinerU job、完成时落地分段），
    不依赖前端轮询；每轮随机限量刷新，失败仅记日志；文档到终态时同步收尾
    其关联任务（success/failed）——同步队列覆盖「下载→解析→可检索」全周期；
    文档状态也可能被知识列表页 5s 前端轮询直接推进到终态（该路径不回写任务），
    由 (c') 孤儿收尾兜底：每轮扫描「文档已终态、任务仍 running」直接收尾，
    否则任务卡 running 直到 30min 回收窗口重跑下载；
(d) 逐任务：锁源 → 现取节点元数据 → 下载 → content_hash 未变跳过 /
    更新预建 LibraryDocument 行并提交解析 → 回写映射；任务保持 running
    直到解析结束（txt/md/csv 直读秒完成的立即终态）；
(e) 收尾：任务所属 run 若全部任务终态 → 按既有规则置 success/partial/failed。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update

from kb_common.config import get_settings
from kb_common.models import (
    KnowledgeLibrary, LibraryDocument, SyncDocumentMapping, SyncFailure, SyncLog,
    SyncRun, SyncSource, SyncTask,
)

from .engine import SyncEngine, _local_storage_dir, _meta_hash
from .export_service import safe_name
from .runtime import WORKER_LOCK, source_lock
from .sync_database import SyncSessionLocal
from .sync_settings import make_dingtalk_client, make_library_backend

logger = logging.getLogger(__name__)


def run_sync_batch_tick(job_log=None) -> tuple[int, str]:
    """批处理一轮入口（XXL-Job syncBatch handler / 降级线程共用）。"""
    s = get_settings()
    tasks: list[int] = []
    try:
        with SyncSessionLocal() as db:
            # (a) 自愈：认领后进程中断的 running 任务回退 pending（下轮重新处理）。
            # 任务生命周期已覆盖解析：文档仍在 PARSING 的 running 任务不回收——
            # 解析大文件常超 30 分钟，回退会导致重复下载/上传。
            reclaim_before = datetime.now() - timedelta(seconds=s.sync_batch_running_reclaim_seconds)
            stale = db.query(SyncTask).filter(
                SyncTask.status == "running",
                SyncTask.library_document_id.isnot(None),
                SyncTask.started_at.isnot(None),
                SyncTask.started_at < reclaim_before,
            ).all()
            for t in stale:
                doc_row = None
                try:
                    doc_row = db.query(LibraryDocument).filter_by(
                        id=uuid.UUID(t.library_document_id)).first()
                except ValueError:
                    doc_row = None
                if doc_row is not None and doc_row.status == "PARSING":
                    continue  # 解析中：等 refresh 段收尾，不回收重跑
                t.status = "pending"
                t.error = ""
            db.commit()

            # (b) 原子认领：跨源全局 FIFO，SKIP LOCKED 防多 tick 并发重复领取。
            # 必须先于 refresh 执行：refresh 受外部服务延迟影响可能耗时数分钟，
            # 排在前面会饿死认领（新任务迟迟不流转 running，run 被看门狗收编）。
            claimed = db.execute(
                select(SyncTask)
                .where(SyncTask.status == "pending", SyncTask.kind == "sync",
                       SyncTask.action.in_(("create", "update")))
                .order_by(SyncTask.id).limit(s.sync_batch_size)
                .with_for_update(skip_locked=True)
            ).scalars().all()
            for t in claimed:
                t.status = "running"
                t.started_at = datetime.now()
                t.finished_at = None
                t.error = ""
                tasks.append(t.id)
            db.commit()  # 释放行锁；running 即「已认领」标记

            # (c) refresh：兜底收割 PARSING 文档的解析状态（每轮随机限量）
            _refresh_parsing_documents(db)
            # (c') 孤儿任务收尾：文档状态可被知识列表页 5s 前端轮询直接推进到
            # 终态（该路径不回写任务），refresh 段只查 PARSING 文档会漏掉它们。
            # 每轮全量兜底「文档已终态、任务仍 running」的组合直接收尾，
            # 保证同步队列与知识列表口径一致（滞后 ≤ 一个 tick 30s）。
            _settle_orphaned_running_tasks()
    except Exception as exc:  # noqa: BLE001
        logger.exception("批处理认领失败")
        if job_log is not None:
            job_log.log(f"批处理认领失败: {exc}")
        return 500, f"批处理认领失败: {exc}"

    ok = failed = 0
    for task_id in tasks:
        outcome, _error = _process_batch_task(task_id)
        if outcome == "failed":
            failed += 1
        elif outcome != "skipped":
            ok += 1
    message = f"批处理完成：领取 {len(tasks)}，成功 {ok}，失败 {failed}"
    logger.info(message)
    if job_log is not None:
        job_log.log(message)
    return 200, message


# ---------- (c) 解析状态兜底 ----------
# 单轮 refresh 限量：僵尸 PARSING 文档（进程崩溃遗留，job 已丢失无法推进）可能
# 积压数百篇，全量刷新会让 tick 长时间不返回（实测 293 篇 >150s）。随机抽样限量
# 保证每轮 tick 时长有界，僵尸文档跨轮轮到；认领已前置，不再受 refresh 拖累。
_REFRESH_DOCS_PER_TICK = 15


def _refresh_parsing_documents(db) -> None:
    """刷新 library 同步源关联的 PARSING 文档（MinerU job 查询 + 完成时落地分段）。

    文档到终态 → 在同步侧收尾其 running 任务（任务生命周期覆盖解析）；
    被前端轮询先行推进到终态的文档由 _settle_orphaned_running_tasks 兜底。
    """
    doc_id_strs = [row[0] for row in db.execute(
        select(SyncDocumentMapping.document_id).distinct()
        .where(SyncDocumentMapping.document_id.isnot(None))
    ).all()]
    if not doc_id_strs:
        return
    uuids = []
    for v in doc_id_strs:
        try:
            uuids.append(uuid.UUID(v))
        except ValueError:
            continue
    rows = db.query(LibraryDocument.id, LibraryDocument.library_id).filter(
        LibraryDocument.id.in_(uuids), LibraryDocument.status == "PARSING") \
        .order_by(func.random()).limit(_REFRESH_DOCS_PER_TICK).all()
    if not rows:
        return
    terminal: set = set()
    try:
        terminal = asyncio.run(_refresh_parsings(set(rows))) or set()
    except Exception as exc:  # noqa: BLE001
        logger.warning("批处理刷新解析状态失败: %s", exc)
    if not terminal:
        return
    # 解析刚到终态的文档：收尾其关联 running 任务。注意必须用同步会话——
    # _settle_tasks_for_document 是同步 ORM（s.query），此前在 _refresh_parsings
    # 的 AsyncSession 上直接调用，每次文档完成都抛 AttributeError 且连文档
    # 状态 commit 一起回滚，任务永远收不了尾。
    with SyncSessionLocal() as sdb:
        for doc_id in terminal:
            doc = sdb.query(LibraryDocument).filter_by(id=doc_id).first()
            if doc is not None:
                _settle_tasks_for_document(sdb, doc)
        sdb.commit()


async def _refresh_parsings(pairs: set) -> set:
    """刷新 PARSING 文档的解析状态；返回本轮到终态的文档 ID 集合。

    任务收尾在同步侧进行（调用方 _refresh_parsing_documents）——历史 bug：
    本函数曾直接在 AsyncSession 上调同步 _settle_tasks_for_document，
    AttributeError 导致收尾路径全断，详见调用方注释。
    """
    from kb_common.database import fresh_session

    from app.routes.managed_library import engine as get_engine
    from app.routes.managed_library import refresh_state
    adapter = get_engine()
    terminal: set = set()
    # 独立短命引擎：执行器线程的临时事件循环不能复用绑定主 loop 的全局连接池
    async with fresh_session() as s:
        for doc_id, library_id in pairs:
            try:
                lib = await s.get(KnowledgeLibrary, library_id)
                doc = await s.get(LibraryDocument, doc_id)
                if lib is None or doc is None:
                    continue
                await refresh_state(adapter, s, lib, doc)
                if doc.status in ("COMPLETED", "FAILED", "CANCELLED"):
                    terminal.add(doc_id)
                await s.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("刷新文档 %s 解析状态失败: %s", doc_id, exc)
    return terminal


def _settle_tasks_for_document(s, doc) -> None:
    """文档解析终态 → 回写其关联 running 同步任务（成功/失败/取消）。

    任务 running 期间（解析中）不 bump 计数，在这里按最终结果补记，
    保证 run 的 created/updated/failed 计数与任务终态一致。
    """
    from datetime import datetime

    tasks = s.query(SyncTask).filter(
        SyncTask.library_document_id == str(doc.id),
        SyncTask.status == "running",
    ).all()
    for t in tasks:
        if doc.status == "COMPLETED":
            t.status, t.error = "success", ""
            t.finished_at = datetime.now()
            _bump_run(s, t.run_id, "updated" if t.action == "update" else "created")
        else:
            t.status = "failed"
            t.error = f"解析{'失败' if doc.status == 'FAILED' else '已取消'}: {doc.message or ''}"[:2000]
            t.finished_at = datetime.now()
            _bump_run(s, t.run_id, "failed")
        _finalize_run_if_done(s, t.run_id)


def _settle_orphaned_running_tasks() -> int:
    """收尾被外部路径先行推进到终态的文档的 running 任务，返回收尾文档数。

    知识列表页每 5s 对 PARSING 文档调 POST /documents/{id}/refresh，文档可直接
    被推进到 COMPLETED/FAILED —— 该路径不回写 SyncTask；而 (c) refresh 段只查
    status=="PARSING" 的文档，被前端先推进的文档永远轮不到收尾，任务会卡
    running 直到 30min 回收窗口回退 pending 重跑下载。这里每轮兜底扫描
    「文档已终态、任务仍 running」的组合，按文档终态直接收尾（幂等：只动
    running 任务；与 _process_locked 的终态回写语义一致）。

    认领豁免：只收「文档终态出现在任务认领之后」的组合（updated_at > started_at）。
    重试场景里文档带着**认领前**的旧失败终态（如上轮下载失败留下的
    「同步失败: ...」），任务刚被认领还没执行——此时收尾等于用旧状态把重试
    任务打死（重试永远失败的死循环）；正确路径是让 _process_batch_task 重新
    下载上传，把文档重置回 UPLOADED/PARSING。外部推进（前端 refresh）必然
    发生在认领之后，不受影响；started_at 缺失的存量任务仍按旧行为兜底收尾。
    """
    with SyncSessionLocal() as db:
        # 同文档多个 running 任务取最新认领时间：任一任务认领晚于文档终态
        # 即视为外部推进，正常兜底；全部任务都早于终态才豁免。
        claimed_at: dict[str, datetime] = {}
        for lib_doc_id, started_at in db.query(
                SyncTask.library_document_id, SyncTask.started_at).filter(
                SyncTask.status == "running",
                SyncTask.library_document_id.isnot(None)).all():
            try:
                key = str(uuid.UUID(lib_doc_id))
            except (ValueError, TypeError):
                continue
            ts = started_at or datetime.min
            if key not in claimed_at or ts > claimed_at[key]:
                claimed_at[key] = ts
        if not claimed_at:
            return 0
        docs = db.query(LibraryDocument).filter(
            LibraryDocument.id.in_([uuid.UUID(k) for k in claimed_at]),
            LibraryDocument.status.in_(("COMPLETED", "FAILED", "CANCELLED")),
        ).all()
        settle_docs = []
        for doc in docs:
            latest_claim = claimed_at.get(str(doc.id), datetime.min)
            if doc.updated_at and doc.updated_at <= latest_claim:
                continue  # 终态早于认领：旧状态残留，交给消费主路径重新上传重置
            settle_docs.append(doc)
        for doc in settle_docs:
            _settle_tasks_for_document(db, doc)
        if settle_docs:
            db.commit()
        return len(settle_docs)


# ---------- (d) 逐任务处理 ----------

def _reset_stale_doc_for_retry(db, task: SyncTask) -> bool:
    """状态口径统一：任务已认领开始处理（下载/上传/解析在途），文档若停留在
    上一轮的失败终态，先回到 PARSING（处理中）——知识列表与同步队列同时
    显示「处理中」，消除「文档解析失败、队列还在处理中」的割裂观感。

    只动 FAILED/CANCELLED（重试对象）：COMPLETED 的更新任务在下载完成前
    旧内容仍可检索，保持已上传状态；下载/上传失败由 _record_task_failure
    重新置回 FAILED（覆盖 PARSING），成功路径由 upload_file 重新进入解析。
    返回是否发生了重置（发生重置的即使内容未变也要重新提交解析）。
    """
    if not task.library_document_id:
        return False
    try:
        doc_uuid = uuid.UUID(task.library_document_id)
    except ValueError:
        return False
    doc = db.query(LibraryDocument).filter_by(id=doc_uuid).first()
    if doc is not None and doc.status in ("FAILED", "CANCELLED"):
        doc.status = "PARSING"
        doc.message = "同步重新处理中..."
        db.commit()
        return True
    return False


def _should_skip_reupload(mapping, content_hash: str, doc_row) -> bool:
    """增量跳过判定：上一轮已同步且内容未变。

    文档解析失败的（FAILED/CANCELLED）不跳过——重传同一文件重新提交解析
    （外部解析服务可能是瞬时故障，重试解析有机会成功），避免「队列 success、
    文档永远 FAILED」的反向不一致。
    """
    if mapping is None or mapping.status != "synced" or mapping.content_hash != content_hash:
        return False
    return doc_row is None or doc_row.status not in ("FAILED", "CANCELLED")


def _process_batch_task(task_id: int) -> tuple[str, str]:
    """处理单个已认领任务；返回 (outcome, error)。"""
    with SyncSessionLocal() as db:
        task = db.get(SyncTask, task_id)
        if task is None or task.status != "running":
            return "skipped", "任务已不在处理中"
        source = db.get(SyncSource, task.source_id) if task.source_id else None
        if source is None or not source.enabled:
            _finish_task(db, task, "failed", "同步源已停用或已删除，任务取消")
            _bump_run(db, task.run_id, "failed")
            _finalize_run_if_done(db, task.run_id)
            return "failed", "同步源已停用或已删除"
        # 预建文档行已不存在（用户手动删除）：任务取消；下轮编目会预建新行重新同步
        if task.library_document_id:
            try:
                doc_uuid = uuid.UUID(task.library_document_id)
            except ValueError:
                doc_uuid = None
            doc_exists = doc_uuid is not None and db.query(LibraryDocument.id).filter_by(
                id=doc_uuid).first() is not None
            if not doc_exists:
                mapping = _mapping_for(db, source.id, task.node_id)
                if mapping is not None:
                    mapping.status = "error"
                    mapping.error = "目标文档已被删除"
                _finish_task(db, task, "failed", "目标文档已被删除，任务取消")
                _bump_run(db, task.run_id, "failed")
                _finalize_run_if_done(db, task.run_id)
                return "failed", "目标文档已被删除"
        # 源被编目/同批其他任务占用：回退 pending，下轮再试
        with source_lock(source.id, WORKER_LOCK) as free:
            if not free:
                task.status = "pending"
                task.started_at = None
                task.error = ""
                db.commit()
                return "skipped", "同步源正忙，任务回退待处理"
            return _process_locked(db, task, source)


def _process_locked(db, task: SyncTask, source: SyncSource) -> tuple[str, str]:
    """已持有源锁的单任务处理：下载 → 增量跳过/上传 → 回写映射与任务状态。"""
    dt = None
    backend = None
    node_id = task.node_id or ""
    name = task.name
    try:
        # 处理开始即对齐文档状态：旧失败终态 → PARSING（下载/上传期间知识列表
        # 与同步队列同为「处理中」）；发生重置的文档本轮必定重新提交解析
        retried_parse = _reset_stale_doc_for_retry(db, task)
        from app.services.dingtalk_operator import resolve_source_operator_sync
        op_union, _tag = resolve_source_operator_sync(db, source)
        dt = make_dingtalk_client(db, operator_union_id=op_union)
        backend = make_library_backend(source)
        library_id = backend.library_id

        # 节点元数据现取（永远新鲜；钉钉侧已删除时由此报错）
        response = dt.get_node(node_id)
        node = response.get("node") or response
        if not node.get("name"):
            raise RuntimeError("钉钉未返回节点元数据，无法确定源文件类型")
        node = {**node, "nodeId": node_id}

        # 下载复用引擎 _fetch（含源文档 MinIO 备份）
        engine = SyncEngine(source)
        rel_dir = Path(node.get("relative_dir", "").strip("/"))
        base_dir = _local_storage_dir() / str(source.id)
        local_file, content_hash = engine._fetch(dt, node, name, base_dir, rel_dir)

        mapping = _mapping_for(db, source.id, node_id)
        # 增量跳过：上一轮已同步且内容未变化（与 engine _process_node 同口径）；
        # 文档解析失败的重新提交解析（_should_skip_reupload）
        doc_row = None
        if mapping is not None and mapping.document_id:
            try:
                doc_row = db.query(LibraryDocument).filter_by(
                    id=uuid.UUID(mapping.document_id)).first()
            except ValueError:
                doc_row = None
        if _should_skip_reupload(mapping, content_hash, doc_row) and not retried_parse:
            # 内容未变不重新上传；任务终态同样跟随文档解析状态——
            # 文档仍在 PARSING（上一轮提交的解析未收尾）时保持 running，
            # 由 tick refresh 段在解析结束时收尾，避免口径断裂
            if task is not None:
                if doc_row is not None and doc_row.status == "PARSING":
                    task.status = "running"
                    task.finished_at = None
                else:
                    task.status = "success"
                    task.finished_at = datetime.now()
                task.error = ""
            mapping.name = name
            mapping.meta_hash = _meta_hash(node)
            db.commit()
            _finalize_run_if_done(db, task.run_id)
            return "skipped", ""

        was_update = task.action == "update"
        # 更新预建行 + 非阻塞提交解析（UPLOADED → PARSING；txt/md/csv 直接 COMPLETED）
        result = backend.upload_file(str(library_id), local_file,
                                      file_name=local_file.name,
                                      doc_id=task.library_document_id)
        doc_id = (result.get("document") or {}).get("id")
        if not doc_id:
            raise RuntimeError("目标文档库上传未返回文档 ID")

        # 回写映射（上传成功即视为同步完成；解析由 tick refresh 兜底收割）
        if mapping is None:
            mapping = SyncDocumentMapping(source_id=source.id, node_id=node_id,
                                          name=name, category=node.get("category", ""))
            db.add(mapping)
        mapping.document_id = doc_id
        mapping.parent_node_id = node.get("parent_node_id", source.root_node_id)
        mapping.name = name
        mapping.relative_path = str(rel_dir / safe_name(name))
        mapping.category = node.get("category", "")
        mapping.meta_hash = _meta_hash(node)
        mapping.content_hash = content_hash
        mapping.local_path = str(local_file)
        mapping.status = "synced"
        mapping.error = ""
        mapping.last_synced_at = datetime.now()

        # 任务终态跟随文档解析：同步（下载/上传）完成即 mapping=synced，但任务
        # 保持 running 直到解析结束——PARSING 由 tick refresh 段收尾，txt/md/csv
        # 本地直读已 COMPLETED 的立即 success。同步队列由此覆盖完整生命周期
        # （下载 → 解析 → 可检索），与知识列表状态口径一致。
        doc_row = None
        try:
            doc_row = db.query(LibraryDocument).filter_by(
                id=uuid.UUID(doc_id)).first()
        except ValueError:
            doc_row = None
        if doc_row is not None and doc_row.status == "PARSING":
            task.status = "running"
            task.finished_at = None
        else:
            task.status = "success"
            task.finished_at = datetime.now()
        task.error = ""
        if doc_row is not None and doc_row.status == "FAILED":
            task.status = "failed"
            task.finished_at = datetime.now()
            task.error = f"解析失败: {doc_row.message or ''}"[:2000]
        try:
            task.file_size = local_file.stat().st_size
        except OSError:
            task.file_size = None
        task.file_ext = local_file.suffix.lower().lstrip(".") or task.file_ext
        db.query(SyncFailure).filter_by(source_id=source.id, node_id=node_id).delete()
        db.commit()
        if task.status != "running":
            _bump_run(db, task.run_id, "updated" if was_update else "created")
        _finalize_run_if_done(db, task.run_id)
        return ("updated" if was_update else "created"), ""
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        logger.error("批处理任务失败 [%s]: %s", name, error)
        db.rollback()
        task = db.get(SyncTask, task.id)
        if task is not None:
            _record_task_failure(db, task, source, node_id, name, error)
        return "failed", error
    finally:
        if dt is not None:
            dt.close()
        if backend is not None:
            backend.close()


def _record_task_failure(db, task: SyncTask, source: SyncSource,
                         node_id: str, name: str, error: str) -> None:
    """任务失败落库：task failed + mapping error + SyncFailure + 预建文档标 FAILED。"""
    task.status = "failed"
    task.finished_at = datetime.now()
    task.error = error[:2000]
    mapping = _mapping_for(db, source.id, node_id)
    if mapping is not None:
        mapping.status = "error"
        mapping.error = error[:2000]
    else:
        db.add(SyncDocumentMapping(source_id=source.id, node_id=node_id, name=name,
                                   status="error", error=error[:2000]))
    db.add(SyncFailure(run_id=task.run_id, source_id=source.id, node_id=node_id,
                       name=name, error=error[:2000]))
    # 下载/上传/解析提交失败：把预建文档行标 FAILED（仍在 PENDING/UPLOADED 时）
    if task.library_document_id:
        try:
            doc = db.query(LibraryDocument).filter_by(
                id=uuid.UUID(task.library_document_id)).first()
            if doc is not None and doc.status in ("PENDING", "UPLOADED", "PARSING"):
                doc.status = "FAILED"
                doc.message = f"同步失败: {error}"[:2000]
        except ValueError:
            pass
    db.commit()
    _bump_run(db, task.run_id, "failed")
    _finalize_run_if_done(db, task.run_id)


# ---------- 辅助 ----------

def _mapping_for(db, source_id: int, node_id: str | None):
    if not node_id:
        return None
    return db.query(SyncDocumentMapping).filter_by(
        source_id=source_id, node_id=node_id).first()


def _finish_task(db, task: SyncTask, status: str, message: str) -> None:
    task.status = status
    task.finished_at = datetime.now()
    task.error = "" if status == "success" else message[:2000]
    db.commit()


def _bump_run(db, run_id: int | None, field: str) -> None:
    """run 计数原子自增（仅 running 中的 run；终态 run 不再回写，审计以任务行为准）。"""
    if run_id is None:
        return
    column = {"created": SyncRun.created_count, "updated": SyncRun.updated_count,
              "failed": SyncRun.failed_count}[field]
    db.execute(update(SyncRun).where(SyncRun.id == run_id, SyncRun.status == "running")
               .values({column: column + 1}))
    db.commit()


def _finalize_run_if_done(db, run_id: int | None) -> None:
    """run 的全部任务终态时收尾（幂等；判定规则与 engine 直跑模式一致）。"""
    if run_id is None:
        return
    run = db.query(SyncRun).filter_by(id=run_id, status="running").with_for_update().first()
    if run is None:
        return
    remaining = db.query(SyncTask).filter(
        SyncTask.run_id == run_id,
        SyncTask.status.in_(("pending", "running")),
    ).count()
    if remaining:
        return
    created = run.created_count or 0
    updated = run.updated_count or 0
    deleted = run.deleted_count or 0
    failed = run.failed_count or 0
    total = run.total or 0
    skipped = max(total - created - updated - deleted - failed, 0)
    run.finished_at = datetime.now()
    if failed == 0:
        run.status = "success"
    elif created + updated + deleted + skipped == 0:
        run.status = "failed"
    else:
        run.status = "partial"
    run.message = (f"批处理完成 total={total} skipped={skipped} created={created} "
                   f"updated={updated} deleted={deleted} failed={failed}")
    db.add(SyncLog(run_id=run_id,
                   level="INFO" if run.status == "success" else "WARNING",
                   message=run.message))
    db.commit()
    # 单次导入源：本轮全部成功即完成使命（失败保持启用，由 cron 增量重试）
    if failed == 0:
        retire_import_once(db, run.source_id)


def retire_import_once(db, source_id: int | None) -> None:
    """单次导入源收编：源已无未消费任务时停用源（幂等，best effort）。

    仅在 import_once 且该源队列已清空时生效。定时编目已取消，
    不再存在需要停用的 cron 作业。
    """
    if not source_id:
        return
    source = db.get(SyncSource, source_id)
    if source is None or not source.import_once or not source.enabled:
        return
    pending = db.query(SyncTask).filter(
        SyncTask.source_id == source_id,
        SyncTask.status.in_(("pending", "running"))).count()
    if pending:
        return
    source.enabled = False
    db.commit()
    logger.info("单次导入源 %s 已完成，自动停用", source_id)
