"""钉钉知识库 → 本地文档库 定时增量同步路由。

- 前缀：/api/v1/sync
- 认证：沿用平台 require_role（super_admin/admin/editor）
- DB：同步引擎用同步 SessionLocal（SyncSessionLocal），路由内 CRUD 也用同步会话
- 立即同步/重试用 ThreadPoolExecutor 提交，不阻塞请求
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, literal, func, cast, String, tuple_

from app.deps import require_role
from app.schemas import (
    SyncFailureOut, SyncLogOut, SyncRunOut,
    SyncPreviewSettingsUpdate, SyncSourceCreate, SyncSourceOut, SyncSourceTest, SyncSourceUpdate,
    SyncTaskBatchIn, SyncTaskOut,
)
from kb_common.models import (
    LibraryDocument, SyncDocumentMapping, SyncFailure, SyncLog, SyncRun, SyncSource, SyncTask,
)

from app.services.sync.dingtalk_sync_client import DingTalkError
from app.services.sync.engine import run_sync
from app.services.sync.export_service import check_dws
from app.services.sync.source_files import skip_reason
from app.services.sync.scheduler import remove_source_job
from app.services.sync.sync_database import get_sync_session
from app.services.sync.sync_settings import make_dingtalk_client, make_library_backend

router = APIRouter(prefix="/api/v1/sync", tags=["同步"])
_executor = ThreadPoolExecutor(max_workers=4)


def get_sync_db():
    """同步 DB 会话依赖（每次请求一个会话，请求结束自动关闭）。"""
    db = get_sync_session()
    try:
        yield db
    finally:
        db.close()


# ---------- 钉钉目录（配置同步源用）----------
@router.get("/activity", dependencies=[Depends(require_role("super_admin", "admin"))])
def collection_activity(kind: str = "", status: str = "", keyword: str = "",
                        page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                        db=Depends(get_sync_db)):
    conditions = []
    if kind:
        conditions.append(literal("directory") == kind)
    if keyword.strip():
        conditions.append(SyncSource.name.contains(keyword.strip(), autoescape=True))
    groups = db.execute(select(literal("directory"), SyncRun.status, func.count().label("count"))
        .join(SyncSource, SyncSource.id == SyncRun.source_id)
        .where(*conditions).group_by(SyncRun.status)).mappings().all()
    if status:
        conditions.append(SyncRun.status == status)
    total = db.scalar(select(func.count()).select_from(SyncRun)
                      .join(SyncSource, SyncSource.id == SyncRun.source_id).where(*conditions))
    rows = db.execute(select(SyncRun, SyncSource.name.label("source_name"))
        .join(SyncSource, SyncSource.id == SyncRun.source_id)
        .where(*conditions)
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .offset((page - 1) * size).limit(size)).all()
    items = [{
        "id": run.id, "kind": "directory", "name": source_name,
        "source_id": run.source_id, "message": run.message,
        "status": run.status, "started_at": run.started_at, "finished_at": run.finished_at,
        "total": run.total,
        "success_count": run.created_count + run.updated_count + run.deleted_count,
        "failed_count": run.failed_count, "document_id": None, "trigger": run.trigger,
    } for run, source_name in rows]
    return {"items": items, "total": total, "groups": [dict(row) for row in groups]}


@router.get("/dingtalk/workspaces",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def dingtalk_workspaces(db=Depends(get_sync_db)):
    dt = make_dingtalk_client(db)
    try:
        return dt.list_workspaces()
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"获取知识库失败: {exc}")
    finally:
        dt.close()


@router.get("/dingtalk/tree",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def dingtalk_tree(root_node_id: str = Query(...), depth: int = Query(5, le=20),
                  db=Depends(get_sync_db)):
    from kb_common.config import get_settings
    s = get_settings()
    dt = make_dingtalk_client(db)
    try:
        return dt.build_tree(root_node_id, max_depth=depth,
                             max_results=s.sync_max_results_per_page)
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"获取目录树失败: {exc}")
    finally:
        dt.close()


@router.get("/dingtalk/nodes",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def dingtalk_nodes(parent_node_id: str = Query(...), max_results: int = Query(50, le=100),
                   db=Depends(get_sync_db)):
    """子目录懒加载（配置同步源表单的目录树用）。"""
    dt = make_dingtalk_client(db)
    try:
        nodes = dt.list_nodes(parent_node_id, max_results=max_results)
        return [{
            "nodeId": n.get("nodeId", ""),
            "name": n.get("name", n.get("nodeId", "")),
            "category": n.get("category", ""),
            "hasChildren": bool(n.get("hasChildren", False)),
        } for n in nodes]
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"获取子目录失败: {exc}")
    finally:
        dt.close()


# ---------- 同步源 ----------
def _serialize_node_whitelist(value) -> str:
    """node_whitelist 在 schema 里是 list，ORM 列是 Text，存 JSON 字符串。"""
    import json as _json
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value or "[]"
    return _json.dumps(value, ensure_ascii=False)


@router.get("/sources", response_model=list[SyncSourceOut],
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def list_sources(db=Depends(get_sync_db)):
    return db.query(SyncSource).order_by(SyncSource.id.desc()).all()


# 注意：本路由必须声明在所有 /sources/{source_id} 路由之前，
# 否则 "stats" 会被当成 source_id 匹配掉，返回 422。
@router.get("/sources/stats",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def sources_stats_all(db=Depends(get_sync_db)):
    """所有同步源的文档数 + 最近一次运行（批量版）。

    替代前端「逐源并发请求 /sources/{id}/stats」的 N+1 模式：
    钉钉知识同步页每 3 秒轮询一次、每次 2+N 个请求，N 个源就是 N 条连接，
    是连接池被抽干、整站点击卡顿的主要来源之一。这里两条聚合查询搞定。
    """
    source_ids = db.execute(select(SyncSource.id)).scalars().all()
    doc_counts = dict(db.execute(
        select(SyncDocumentMapping.source_id, func.count(SyncDocumentMapping.id))
        .where(SyncDocumentMapping.status == "synced")
        .group_by(SyncDocumentMapping.source_id)).all())
    # PostgreSQL DISTINCT ON：每个源按开始时间倒序取最新一条运行记录
    latest_runs = db.execute(
        select(SyncRun)
        .distinct(SyncRun.source_id)
        .order_by(SyncRun.source_id, SyncRun.started_at.desc())
    ).scalars().all()
    run_by_source = {r.source_id: r for r in latest_runs}
    return {"items": [{
        "source_id": sid,
        "doc_count": doc_counts.get(sid, 0),
        "last_run": SyncRunOut.model_validate(run_by_source[sid]).model_dump()
                    if sid in run_by_source else None,
    } for sid in source_ids]}


@router.post("/sources", response_model=SyncSourceOut,
             dependencies=[Depends(require_role("super_admin", "admin"))])
def create_source(payload: SyncSourceCreate, u=Depends(require_role("super_admin", "admin")),
                  db=Depends(get_sync_db)):
    data = payload.model_dump()
    if not (data.get("dataset_name") or "").strip():
        raise HTTPException(status_code=422, detail="请选择目标知识库")
    data["node_whitelist"] = _serialize_node_whitelist(data.get("node_whitelist"))
    if not (data.get("dataset_id") or "").strip():
        raise HTTPException(status_code=422, detail="请指定目标文档库")
    client = make_library_backend(data)
    try:
        dataset = client.resolve_dataset(data.get("dataset_id"), data["dataset_name"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        client.close()
    data.update(dataset_id=dataset["id"], dataset_name=dataset["name"])
    # 同步身份归属：默认记创建者（后台同步用其钉钉权限拉取）；body 可显式指定/置空
    import uuid as _uuid
    owner_raw = data.get("owner_user_id") or str(u.id)
    data["owner_user_id"] = _uuid.UUID(owner_raw) if isinstance(owner_raw, str) else owner_raw
    source = SyncSource(**data)
    db.add(source)
    db.commit()
    db.refresh(source)
    # 「添加知识」：创建后立即跑首次同步（进程内直跑编目），
    # 后续更新由钉钉知识库变更事件自动触发（事件监听 → 整源增量编目）。
    if source.enabled:
        from app.services.sync.scheduler import trigger_first_sync
        trigger_first_sync(source.id, getattr(u, "username", "") or "")
    return source


@router.get("/sources/{source_id}", response_model=SyncSourceOut,
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def get_source(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    return source


@router.put("/sources/{source_id}", response_model=SyncSourceOut,
            dependencies=[Depends(require_role("super_admin", "admin"))])
def update_source(source_id: int, payload: SyncSourceUpdate, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "dataset_name" in updates and not (updates.get("dataset_name") or "").strip():
        raise HTTPException(status_code=422, detail="请选择目标知识库")
    if "node_whitelist" in updates:
        updates["node_whitelist"] = _serialize_node_whitelist(updates.get("node_whitelist"))
    if "owner_user_id" in updates:
        import uuid as _uuid
        raw = updates["owner_user_id"]
        updates["owner_user_id"] = _uuid.UUID(raw) if raw else None
    if "dataset_id" in updates or "dataset_name" in updates:
        target_id = updates.get("dataset_id", source.dataset_id)
        if not (target_id or "").strip():
            raise HTTPException(status_code=422, detail="请指定目标文档库")
        client = make_library_backend({"dataset_id": target_id})
        try:
            # 兼容旧前端只按名称改目标；新前端始终携带 ID。
            if "dataset_id" not in updates and updates.get("dataset_name") != source.dataset_name:
                target_id = None
            dataset = client.resolve_dataset(target_id, updates.get("dataset_name") or source.dataset_name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            client.close()
        if source.dataset_id and dataset["id"] != source.dataset_id:
            if db.query(SyncRun).filter_by(source_id=source_id, status="running").first():
                raise HTTPException(409, "同步运行中，不能更换目标知识库")
            for mapping in db.query(SyncDocumentMapping).filter_by(source_id=source_id):
                mapping.document_id = None
                mapping.batch_id = None
                mapping.status = "pending"
                mapping.error = ""
            db.query(SyncFailure).filter_by(source_id=source_id).delete()
        updates.update(dataset_id=dataset["id"], dataset_name=dataset["name"])
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    if "owner_user_id" in updates:
        from app.services import dingtalk_operator
        dingtalk_operator.invalidate_source(source_id)
    return source


@router.delete("/sources/{source_id}",
               dependencies=[Depends(require_role("super_admin", "admin"))])
def delete_source(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    job_id = source.xxl_job_id
    db.delete(source)
    db.commit()
    remove_source_job(job_id)
    return {"ok": True}


@router.post("/sources/{source_id}/sync",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def sync_source_now(source_id: int, u=Depends(require_role("super_admin", "admin", "editor")),
                    db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="同步源已停用，启用后才可立即同步")
    from app.services.sync.scheduler import trigger_source_sync
    result = trigger_source_sync(source_id, u.username)
    return {"ok": True, "via": result["via"], "message": result["message"]}


@router.get("/sources/{source_id}/stats",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def source_stats(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    # 文档数 = 该同步源已成功同步的文档数（本地映射 status=synced）。
    # 多个源可共享同一文档库（且文档库可能含手动上传文档），
    # 不能用全库文档数作为单源口径。
    doc_count = db.query(func.count(SyncDocumentMapping.id)).filter(
        SyncDocumentMapping.source_id == source_id,
        SyncDocumentMapping.status == "synced",
    ).scalar() or 0
    last_run = db.query(SyncRun).filter(SyncRun.source_id == source_id) \
        .order_by(SyncRun.started_at.desc()).first()
    return {"doc_count": doc_count,
            "last_run": SyncRunOut.model_validate(last_run).model_dump() if last_run else None}


def _test_source_connection(dataset_name: str, db, dataset_id: str | None = None) -> dict[str, Any]:
    """测试当前草稿的外部依赖，不要求同步源已写入数据库。"""
    results: dict[str, Any] = {}
    dt = make_dingtalk_client(db)
    try:
        results["dingtalk"] = dt.test_connection()
    except DingTalkError as exc:
        results["dingtalk"] = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        results["dingtalk"] = {"ok": False, "error": str(exc)}
    finally:
        dt.close()

    try:
        backend = make_library_backend({"dataset_id": dataset_id})
        dataset = backend.resolve_dataset(dataset_id, dataset_name)
        results["library"] = {"ok": True, "dataset_id": dataset.get("id")}
    except ValueError as exc:
        results["library"] = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        results["library"] = {"ok": False, "error": str(exc)}

    results["dws"] = check_dws()
    results["ok"] = bool(results.get("dingtalk", {}).get("ok")
                         and results.get("library", {}).get("ok"))
    return results


@router.post("/sources/test",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def test_source_draft(payload: SyncSourceTest, db=Depends(get_sync_db)):
    """保存前测试表单中选定的钉钉与目标文档库连接。"""
    return _test_source_connection(payload.dataset_name, db, payload.dataset_id)


@router.post("/sources/{source_id}/test",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def test_source(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    return _test_source_connection(source.dataset_name, db, source.dataset_id)


@router.post("/sources/{source_id}/preview",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def preview_source(source_id: int, refresh: bool = False, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    from kb_common.config import get_settings
    s = get_settings()
    dt = make_dingtalk_client(db)
    try:
        # 目录树快照缓存 10 分钟（首次遍历并发 ≤3）；refresh=true 强制重新遍历
        nodes = dt.walk_tree(source.root_node_id, s.sync_max_depth,
                             s.sync_max_results_per_page, use_cache=not refresh)
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"钉钉遍历失败: {exc}")
    finally:
        dt.close()

    mappings = {m.node_id: m for m in
                db.query(SyncDocumentMapping).filter_by(source_id=source_id).all()}
    mode = "library"  # 本地文档库通道：白名单与解析链路均按 library 规则
    items: list[dict] = []
    remote_ids: set[str] = set()
    for node in nodes:
        node_id = node.get("nodeId", "")
        remote_ids.add(node_id)
        name = node.get("name", node_id)
        mapping = mappings.get(node_id)
        if mapping is not None and not mapping.enabled:
            items.append({"node_id": node_id, "name": name, "category": node.get("category", "DOCUMENT"),
                          "enabled": False, "action": "跳过", "doc": name, "note": "已关闭，不参与同步"})
            continue
        reason = skip_reason(node, s, mode)
        if reason:
            items.append({"node_id": node_id, "name": name, "category": node.get("category", "DOCUMENT"),
                          "enabled": True, "action": "跳过", "doc": name, "note": reason})
            continue
        item_base = {"node_id": node_id, "name": name, "category": node.get("category", "DOCUMENT"), "enabled": True}
        if mapping is None:
            items.append({**item_base, "action": "新增", "doc": name, "note": "未同步过，本次将写入目标文档库"})
        else:
            items.append({**item_base, "action": "更新", "doc": name,
                          "note": "上一轮已同步，本次将重新上传" if mapping.status == "synced"
                          else "上次同步失败，将重试"})
    if source.delete_policy == "sync":
        for node_id, mapping in mappings.items():
            if node_id not in remote_ids:
                items.append({"action": "删除", "doc": mapping.name,
                              "note": "钉钉侧已删除，将同步删除目标文档库文档"})
    return items


@router.put("/sources/{source_id}/preview-settings",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def update_preview_settings(source_id: int, payload: SyncPreviewSettingsUpdate, db=Depends(get_sync_db)):
    """保存预演清单中每篇文档的开关，供所有后续同步任务复用。"""
    if db.get(SyncSource, source_id) is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    existing = {m.node_id: m for m in db.query(SyncDocumentMapping).filter_by(source_id=source_id).all()}
    for item in payload.items:
        mapping = existing.get(item.node_id)
        if mapping is None:
            mapping = SyncDocumentMapping(source_id=source_id, node_id=item.node_id,
                                          name=item.name or item.node_id,
                                          category=item.category or "DOCUMENT", enabled=item.enabled)
            db.add(mapping)
        else:
            mapping.enabled = item.enabled
    db.commit()
    return {"ok": True}


# ---------- 运行记录 / 失败 / 日志 ----------
@router.get("/runs", response_model=list[SyncRunOut],
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def list_runs(source_id: int | None = None, limit: int = Query(20, le=200),
              offset: int = 0, db=Depends(get_sync_db)):
    query = db.query(SyncRun)
    if source_id is not None:
        query = query.filter(SyncRun.source_id == source_id)
    return query.order_by(SyncRun.started_at.desc()).offset(offset).limit(limit).all()


@router.get("/runs/{run_id}",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def get_run(run_id: int, db=Depends(get_sync_db)):
    run = db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    failures = db.query(SyncFailure).filter_by(run_id=run_id).order_by(SyncFailure.id.desc()).all()
    logs = db.query(SyncLog).filter_by(run_id=run_id).order_by(SyncLog.id.asc()).all()
    return {
        "run": SyncRunOut.model_validate(run).model_dump(),
        "failures": [SyncFailureOut.model_validate(f).model_dump() for f in failures],
        "logs": [SyncLogOut.model_validate(l).model_dump() for l in logs],
    }


@router.get("/failures", response_model=list[SyncFailureOut],
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def list_failures(source_id: int | None = None, limit: int = Query(50, le=200),
                  offset: int = 0, db=Depends(get_sync_db)):
    query = db.query(SyncFailure)
    if source_id is not None:
        query = query.filter(SyncFailure.source_id == source_id)
    return query.order_by(SyncFailure.id.desc()).offset(offset).limit(limit).all()


@router.post("/failures/{failure_id}/retry",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def retry_failure(failure_id: int, u=Depends(require_role("super_admin", "admin", "editor")),
                  db=Depends(get_sync_db)):
    failure = db.get(SyncFailure, failure_id)
    if failure is None:
        raise HTTPException(status_code=404, detail="失败记录不存在")
    source_id = failure.source_id
    _executor.submit(run_sync, source_id, "manual", u.username)
    return {"ok": True, "message": "已触发重试"}


@router.post("/failures/retry-all",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def retry_all_failures(u=Depends(require_role("super_admin", "admin", "editor")),
                       db=Depends(get_sync_db)):
    rows = db.query(SyncFailure).all()
    if not rows:
        return {"ok": True, "message": "没有待重试的失败项"}
    source_ids = sorted({r.source_id for r in rows})
    for sid in source_ids:
        _executor.submit(run_sync, sid, "manual", u.username)
    return {"ok": True, "message": f"已触发 {len(source_ids)} 个同步源重试"}


# ---------- 同步队列：逐文档任务 ----------
@router.get("/tasks/stats",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def task_stats(db=Depends(get_sync_db)):
    """页签计数（全局口径）：前端轮询用，与列表解耦、不受筛选影响，保证统计实时。"""
    counts = dict(db.execute(
        select(SyncTask.status, func.count()).group_by(SyncTask.status)).all())
    return {"pending": counts.get("pending", 0), "running": counts.get("running", 0),
            "done": counts.get("success", 0) + counts.get("failed", 0)}


@router.get("/tasks",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def list_tasks(tab: str = Query("done"), status: str = "", source_id: int | None = None,
               ext: str = "", duration: str = "", keyword: str = "",
               start_from: str = "", start_to: str = "",
               page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
               db=Depends(get_sync_db)):
    """同步队列任务列表：tab=pending|running|done 三个页签，done 内可再按执行结果筛选。"""
    conditions = _task_conditions(tab, status, source_id, ext, keyword,
                                  duration, start_from, start_to)

    # 页签计数：全局口径，不受筛选条件影响
    counts = dict(db.execute(
        select(SyncTask.status, func.count()).group_by(SyncTask.status)).all())
    tabs = {"pending": counts.get("pending", 0), "running": counts.get("running", 0),
            "done": counts.get("success", 0) + counts.get("failed", 0)}
    total = db.scalar(select(func.count()).select_from(SyncTask).where(*conditions)) or 0
    rows = db.execute(
        select(SyncTask, SyncSource.name.label("source_name"))
        .outerjoin(SyncSource, SyncSource.id == SyncTask.source_id)
        .where(*conditions).order_by(SyncTask.id.desc())
        .offset((page - 1) * size).limit(size)).all()
    items = []
    for task, source_name in rows:
        data = SyncTaskOut.model_validate(task).model_dump()
        data["source_name"] = source_name or ""
        data["duration_sec"] = (int((task.finished_at - task.started_at).total_seconds())
                                if task.started_at and task.finished_at else None)
        items.append(data)
    return {"items": items, "total": total, "tabs": tabs}


@router.post("/tasks/batch-retry",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def batch_retry_tasks(payload: SyncTaskBatchIn, db=Depends(get_sync_db)):
    """批量重试：仅失败且带节点信息的任务可重试。

    library 批处理模式：任务重入队与批处理并发安全（running run 不阻断）。
    """
    from app.services.sync.task_retry import submit_task_retry
    tasks = db.query(SyncTask).filter(SyncTask.id.in_(payload.ids)).all()
    submitted = 0
    skipped = 0
    for task in tasks:
        if task.status == "failed" and task.node_id and task.source_id is not None:
            submit_task_retry(task.id)
            submitted += 1
        else:
            skipped += 1
    skipped += max(0, len(payload.ids) - len(tasks))
    message = f"已提交 {submitted} 个任务重试"
    if skipped:
        message += f"，跳过 {skipped} 个（非失败或缺节点信息）"
    return {"ok": True, "submitted": submitted, "skipped": skipped, "message": message}


def _task_conditions(tab: str, status: str, source_id: int | None, ext: str,
                     keyword: str, duration: str, start_from: str, start_to: str) -> list:
    """任务列表筛选条件（list_tasks 与 batch-delete-all 共用，口径一致）。"""
    conditions = []
    if tab == "pending":
        conditions.append(SyncTask.status == "pending")
    elif tab == "running":
        conditions.append(SyncTask.status == "running")
    else:
        conditions.append(SyncTask.status.in_(["success", "failed"]))
        if status in ("success", "failed"):
            conditions.append(SyncTask.status == status)
    if source_id is not None:
        conditions.append(SyncTask.source_id == source_id)
    if ext:
        conditions.append(SyncTask.file_ext == ext)
    if keyword.strip():
        conditions.append(SyncTask.name.contains(keyword.strip(), autoescape=True))
    dur_sec = func.extract("epoch", SyncTask.finished_at - SyncTask.started_at)
    if duration == "lt10":
        conditions.append(dur_sec <= 10)
    elif duration == "10_60":
        conditions.append(dur_sec > 10)
        conditions.append(dur_sec <= 60)
    elif duration == "60_300":
        conditions.append(dur_sec > 60)
        conditions.append(dur_sec <= 300)
    elif duration == "gt300":
        conditions.append(dur_sec > 300)
    if start_from:
        try:
            conditions.append(SyncTask.started_at >= datetime.fromisoformat(start_from))
        except ValueError:
            pass
    if start_to:
        try:
            conditions.append(SyncTask.started_at < datetime.fromisoformat(start_to) + timedelta(days=1))
        except ValueError:
            pass
    return conditions


# 集合式批量删除的分块大小：tuple IN 每对 2 个绑定参数，500 对 = 1000 参数，
# 远低于 PG 32767 与现代 SQLite 32766 的单语句参数上限。
_BULK_CHUNK = 500


def _delete_task_rows(db, removable: list) -> tuple[int, int]:
    """删除任务行并联动清理（不提交事务）：映射排除 + 占位文档清理 + run 收尾。

    语义口径：
    - 已成功同步的任务：仅删除队列记录，已同步的知识与映射不受影响；
    - 待处理/失败（未成功同步过）的任务：同时把映射置为「不参与同步」
      （enabled=False，避免自动编目重建任务），并删除预建的「待同步」
      占位文档；需要恢复同步时在「同步列表」重新打开该文档的参与开关即可。

    性能教训：万级任务曾逐行 ORM 删除——上万条 DELETE 往返 + 单条 2 万绑定
    参数的元组 IN 预取，全部堆在单请求单事务里，生产上拖到超时 → HTTP 500
    且整批回滚。现改为分块集合式 UPDATE/DELETE（每块 500 行、常数条 SQL），
    万级秒级完成。synchronize_session="fetch" 让会话内已加载对象同步失效/
    更新（实测 2.0.x：fetch 同步不产生脏对象，后续 commit 不会补发逐行语句），
    调用方持有的对象与 db.get 结果保持一致。
    """
    import uuid as _uuid

    removed = excluded = 0
    run_ids: set = set()
    for start in range(0, len(removable), _BULK_CHUNK):
        chunk = removable[start:start + _BULK_CHUNK]
        run_ids.update(t.run_id for t in chunk if t.run_id)
        keys = [(t.source_id, t.node_id) for t in chunk
                if t.node_id and t.source_id is not None]
        if keys:
            # 未成功同步过的映射：批量排除自动同步（防下轮编目重建任务）
            excluded += db.query(SyncDocumentMapping).filter(
                tuple_(SyncDocumentMapping.source_id, SyncDocumentMapping.node_id).in_(keys),
                SyncDocumentMapping.status != "synced",
                SyncDocumentMapping.enabled == True,  # noqa: E712
            ).update({"enabled": False}, synchronize_session="fetch")

            # 预建的「待同步」占位文档（尚无内容）：批量清理，避免列表残留僵尸行
            doc_ids: set = set()
            for (did,) in db.execute(
                select(SyncDocumentMapping.document_id).where(
                    tuple_(SyncDocumentMapping.source_id, SyncDocumentMapping.node_id).in_(keys),
                    SyncDocumentMapping.status != "synced",
                    SyncDocumentMapping.document_id.isnot(None),
                )
            ):
                try:
                    doc_ids.add(_uuid.UUID(did))
                except (TypeError, ValueError):
                    pass
            doc_id_list = list(doc_ids)
            for i in range(0, len(doc_id_list), _BULK_CHUNK):
                db.query(LibraryDocument).filter(
                    LibraryDocument.id.in_(doc_id_list[i:i + _BULK_CHUNK]),
                    LibraryDocument.status == "PENDING",
                ).delete(synchronize_session="fetch")

        # 任务行本身：分块集合式删除
        removed += db.query(SyncTask).filter(
            SyncTask.id.in_([t.id for t in chunk])
        ).delete(synchronize_session="fetch")

    # 关联 run 若已无未完成任务（任务全被移出），立即收尾——
    # 否则 run 永远 running，后续编目会一直以「上一轮批处理尚未完成」跳过
    if run_ids:
        from app.services.sync.batch import _finalize_run_if_done
        for rid in run_ids:
            _finalize_run_if_done(db, rid)
    return removed, excluded


@router.post("/tasks/batch-delete",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def batch_delete_tasks(payload: SyncTaskBatchIn, db=Depends(get_sync_db)):
    """批量清理选中的任务记录：待处理/成功/失败均可清理，处理中的跳过。"""
    tasks = db.query(SyncTask).filter(SyncTask.id.in_(payload.ids)).all()
    removable = [t for t in tasks if t.status != "running"]
    skipped = len(tasks) - len(removable) + max(0, len(payload.ids) - len(tasks))
    removed, excluded = (_delete_task_rows(db, removable) if removable else (0, 0))
    db.commit()
    message = f"已清理 {removed} 个任务"
    if excluded:
        message += (f"；{excluded} 篇未同步完成的文档已停止自动同步"
                    f"（如需恢复，请在「钉钉知识同步 → 同步列表」重新开启）")
    if skipped:
        message += f"；{skipped} 个处理中或不存在，已跳过"
    return {"ok": True, "removed": removed, "excluded": excluded, "skipped": skipped,
            "message": message}


@router.post("/tasks/batch-delete-all",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def batch_delete_all_tasks(tab: str = Query("done"), status: str = "",
                           source_id: int | None = None, ext: str = "",
                           duration: str = "", keyword: str = "",
                           start_from: str = "", start_to: str = "",
                           db=Depends(get_sync_db)):
    """删除当前范围（页签+筛选）命中的全部任务记录，处理中的除外。

    筛选口径与列表完全一致（_task_conditions），叠加 status != running；
    处理中页签下命中的全是 running → 空集，天然安全。
    """
    conditions = _task_conditions(tab, status, source_id, ext, keyword,
                                  duration, start_from, start_to)
    conditions.append(SyncTask.status != "running")
    tasks = db.query(SyncTask).filter(*conditions).all()
    if not tasks:
        return {"ok": True, "removed": 0, "excluded": 0,
                "message": "当前范围内没有可清理的任务"}
    removed, excluded = _delete_task_rows(db, tasks)
    db.commit()
    message = f"已清理 {removed} 个任务"
    if excluded:
        message += (f"；{excluded} 篇未同步完成的文档已停止自动同步"
                    f"（如需恢复，请在「钉钉知识同步 → 同步列表」重新开启）")
    return {"ok": True, "removed": removed, "excluded": excluded, "message": message}


@router.post("/tasks/{task_id}/retry",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def retry_task(task_id: int, db=Depends(get_sync_db)):
    """任务级重试：只重处理这一个钉钉节点，不整源重跑。

    library 批处理模式任务重入队与批处理并发安全（running run 不阻断）。
    """
    from app.services.sync.task_retry import submit_task_retry
    task = db.get(SyncTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "failed":
        raise HTTPException(status_code=409, detail="仅失败任务可重试")
    if not task.node_id or task.source_id is None:
        raise HTTPException(status_code=409, detail="任务缺少钉钉节点或同步源信息，无法重试")
    submit_task_retry(task_id)
    return {"ok": True, "message": "重试已提交，队列稍后刷新可见结果"}


@router.get("/logs", response_model=list[SyncLogOut],
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def list_logs(run_id: int | None = None, level: str | None = None,
              limit: int = Query(100, le=500), offset: int = 0,
              db=Depends(get_sync_db)):
    query = db.query(SyncLog)
    if run_id is not None:
        query = query.filter(SyncLog.run_id == run_id)
    if level:
        query = query.filter(SyncLog.level == level)
    return query.order_by(SyncLog.id.desc()).offset(offset).limit(limit).all()
