"""钉钉知识库 → Dify 定时增量同步路由（迁移自 DingDingKonwledgePipeline）。

- 前缀：/api/v1/sync
- 认证：沿用平台 require_role（super_admin/admin/editor）
- DB：同步引擎用同步 SessionLocal（SyncSessionLocal），路由内 CRUD 也用同步会话
- 立即同步/重试用 ThreadPoolExecutor 提交，不阻塞请求
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select, literal, func, case, cast, String, union_all

from app.deps import require_role
from app.schemas import (
    SyncFailureOut, SyncLogOut, SyncRunOut,
    SyncPreviewSettingsUpdate, SyncSourceCreate, SyncSourceOut, SyncSourceTest, SyncSourceUpdate,
)
from kb_common.clients.dify_document import dataset_runtime
from kb_common.models import (
    SyncDocumentMapping, SyncFailure, SyncLog, SyncRun, SyncSource, CollectionTransfer,
)

from app.services.sync.dingtalk_sync_client import DingTalkError
from app.services.sync.dify_sync_client import DifyError
from app.services.sync.engine import run_sync
from app.services.sync.export_service import check_dws
from app.services.sync.source_files import skip_reason
from app.services.sync.scheduler import reload_sync_jobs
from app.services.sync.sync_database import get_sync_session
from app.services.sync.sync_settings import make_backend, make_dify_client, make_dingtalk_client

router = APIRouter(prefix="/api/v1/sync", tags=["同步"])
_executor = ThreadPoolExecutor(max_workers=4)

# 数据集 runtime 模式缓存（backend_type:dataset_id → (写入时间, mode)），
# 模式基本不变，10 分钟 TTL，免去预演每次都调 Dify resolve_dataset。
_dataset_runtime_cache: dict[str, tuple[float, str]] = {}


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
    directory = select(
        SyncRun.id.label("id"), literal("directory").label("kind"),
        SyncSource.name.label("name"), SyncRun.source_id.label("source_id"),
        SyncSource.dify_dataset_id.label("dataset_id"), SyncSource.dify_dataset_name.label("dataset_name"),
        SyncRun.status.label("status"), SyncRun.message.label("message"),
        SyncRun.started_at.label("started_at"), SyncRun.finished_at.label("finished_at"),
        SyncRun.total.label("total"),
        (SyncRun.created_count + SyncRun.updated_count + SyncRun.deleted_count).label("success_count"),
        SyncRun.failed_count.label("failed_count"), cast(literal(None), String).label("document_id"),
        SyncRun.trigger.label("trigger"),
    ).join(SyncSource, SyncSource.id == SyncRun.source_id)
    transfer = select(
        CollectionTransfer.id, CollectionTransfer.kind, CollectionTransfer.name, literal(None).label("source_id"),
        CollectionTransfer.dataset_id, literal("").label("dataset_name"),
        CollectionTransfer.status, CollectionTransfer.message,
        CollectionTransfer.started_at, CollectionTransfer.finished_at, literal(1).label("total"),
        case((CollectionTransfer.status == "success", 1), else_=0).label("success_count"),
        case((CollectionTransfer.status == "failed", 1), else_=0).label("failed_count"),
        CollectionTransfer.document_id, literal("manual").label("trigger"),
    )
    activity = union_all(directory, transfer).subquery()
    conditions = []
    if kind:
        conditions.append(activity.c.kind == kind)
    if keyword.strip():
        conditions.append(activity.c.name.contains(keyword.strip(), autoescape=True))
    groups = db.execute(select(activity.c.kind, activity.c.status, func.count().label("count"))
        .where(*conditions).group_by(activity.c.kind, activity.c.status)).mappings().all()
    if status:
        conditions.append(activity.c.status == status)
    total = db.scalar(select(func.count()).select_from(activity).where(*conditions))
    rows = db.execute(select(activity).where(*conditions)
        .order_by(activity.c.started_at.desc(), activity.c.kind, activity.c.id.desc())
        .offset((page - 1) * size).limit(size)).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "groups": [dict(row) for row in groups]}


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
def _serialize_pipeline_inputs(value) -> str:
    """pipeline_inputs 在 schema 里是 dict，ORM 列是 Text，存 JSON 字符串。"""
    import json as _json
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value or "{}"
    return _json.dumps(value, ensure_ascii=False)


@router.get("/pipeline-variables",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def pipeline_variables(dataset_id: str = Query(...), db=Depends(get_sync_db)):
    """返回指定流水线数据集的 input form 变量 schema（分段参数定义）。

    Dify Service API 不暴露变量定义，本接口直连 Dify 自身数据库只读查询
    workflows.rag_pipeline_variables（配置项 dify_db_url）。
    未配置 dify_db_url 或查询失败时读取已导入的 .pipeline 参数定义，
    两者均不可用时前端提供配置导入和 JSON 编辑器。
    """
    from app.services.sync.dify_pipeline_vars import pipeline_form
    client = make_dify_client(db)
    try:
        dataset = client.resolve_dataset(dataset_id)
        mode = dataset_runtime(dataset)
        form = (pipeline_form(dataset_id, client.local_file_node_id(dataset_id))
                if mode == "rag_pipeline" else {"configured": True, "variables": [], "schema_source": "general"})
        return {**form, "runtime_mode": mode}
    except (DifyError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        client.close()


@router.post("/pipeline-schema", dependencies=[Depends(require_role("super_admin", "admin"))])
def import_pipeline_schema(file: UploadFile, dataset_id: str = Query(...), db=Depends(get_sync_db)):
    import json
    from kb_common.models import Setting
    from app.services.sync.pipeline_schema import parse_pipeline, schema_key
    client = make_dify_client(db)
    try:
        dataset = client.resolve_dataset(dataset_id)
        if dataset_runtime(dataset) != "rag_pipeline":
            raise ValueError("普通知识库无需导入流水线配置")
        node_id = client.local_file_node_id(dataset_id)
        schema = parse_pipeline(file.file.read(1024 * 1024 + 1), node_id)
        key = schema_key(client.base_url, dataset_id)
        row = db.get(Setting, key)
        value = json.dumps(schema, ensure_ascii=False)
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value, is_secret=False))
        db.commit()
        return {"configured": True, "runtime_mode": "rag_pipeline", "schema_source": "imported",
                "variables": schema["variables"]}
    except (DifyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        client.close()


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
def create_source(payload: SyncSourceCreate, db=Depends(get_sync_db)):
    data = payload.model_dump()
    if not (data.get("dify_dataset_name") or "").strip():
        raise HTTPException(status_code=422, detail="请选择目标知识库")
    data["pipeline_inputs"] = _serialize_pipeline_inputs(data.get("pipeline_inputs"))
    client = make_backend(data.get("backend_type", "dify"), db)
    try:
        dataset = client.resolve_dataset(data.get("dify_dataset_id"), data["dify_dataset_name"])
    except DifyError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        client.close()
    data.update(dify_dataset_id=dataset["id"], dify_dataset_name=dataset["name"])
    source = SyncSource(**data)
    db.add(source)
    db.commit()
    db.refresh(source)
    # 新建源也必须立即注册 cron；否则只能等服务重启或下一次编辑后才会执行。
    reload_sync_jobs()
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
    if "dify_dataset_name" in updates and not (updates.get("dify_dataset_name") or "").strip():
        raise HTTPException(status_code=422, detail="请选择目标知识库")
    if "pipeline_inputs" in updates:
        updates["pipeline_inputs"] = _serialize_pipeline_inputs(updates.get("pipeline_inputs"))
    if "dify_dataset_id" in updates or "dify_dataset_name" in updates:
        backend_type = updates.get("backend_type") or source.backend_type or "dify"
        client = make_backend(backend_type, db)
        try:
            target_id = updates.get("dify_dataset_id", source.dify_dataset_id)
            # 兼容旧前端只按名称改目标；新前端始终携带 ID。
            if "dify_dataset_id" not in updates and updates.get("dify_dataset_name") != source.dify_dataset_name:
                target_id = None
            dataset = client.resolve_dataset(target_id, updates.get("dify_dataset_name") or source.dify_dataset_name)
        except DifyError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            client.close()
        if source.dify_dataset_id and dataset["id"] != source.dify_dataset_id:
            if db.query(SyncRun).filter_by(source_id=source_id, status="running").first():
                raise HTTPException(409, "同步运行中，不能更换目标知识库")
            for mapping in db.query(SyncDocumentMapping).filter_by(source_id=source_id):
                mapping.dify_document_id = None
                mapping.dify_batch = None
                mapping.status = "pending"
                mapping.error = ""
            db.query(SyncFailure).filter_by(source_id=source_id).delete()
        updates.update(dify_dataset_id=dataset["id"], dify_dataset_name=dataset["name"])
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    reload_sync_jobs()
    return source


@router.delete("/sources/{source_id}",
               dependencies=[Depends(require_role("super_admin", "admin"))])
def delete_source(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    db.delete(source)
    db.commit()
    reload_sync_jobs()
    return {"ok": True}


@router.post("/sources/{source_id}/sync",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def sync_source_now(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="同步源已停用，启用后才可立即同步")
    running = db.query(SyncRun.id).filter(
        SyncRun.source_id == source_id, SyncRun.status == "running",
    ).first()
    if running:
        raise HTTPException(status_code=409, detail="该同步源正在运行，请在运行监控中查看结果")
    _executor.submit(run_sync, source_id, "manual")
    return {"ok": True, "message": "同步任务已启动，可在运行监控中查看结果"}


@router.get("/sources/{source_id}/stats",
            dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def source_stats(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    # 文档数 = 该同步源已成功同步到 Dify 的文档数（本地映射 status=synced）。
    # 多个源可共享同一 Dify 数据集（且数据集可能含手动上传文档），
    # 不能用数据集全库文档数作为单源口径。
    doc_count = db.query(func.count(SyncDocumentMapping.id)).filter(
        SyncDocumentMapping.source_id == source_id,
        SyncDocumentMapping.status == "synced",
    ).scalar() or 0
    last_run = db.query(SyncRun).filter(SyncRun.source_id == source_id) \
        .order_by(SyncRun.started_at.desc()).first()
    return {"doc_count": doc_count,
            "last_run": SyncRunOut.model_validate(last_run).model_dump() if last_run else None}


def _test_source_connection(dify_dataset_name: str, db, dataset_id: str | None = None,
                            backend_type: str = "dify") -> dict[str, Any]:
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

    backend = make_backend(backend_type, db)
    is_dify = (backend_type or "dify") == "dify"
    try:
        dataset = backend.resolve_dataset(dataset_id, dify_dataset_name)
        if dataset is None:
            results["dify"] = {"ok": False, "error": f"知识库不存在: {dify_dataset_name}"}
        elif is_dify and dataset_runtime(dataset) == "rag_pipeline":
            # Dify 知识流水线数据集走 pipeline/run 通道，需确认已发布流水线含本地文件数据源节点。
            try:
                node_id = backend.local_file_node_id(dataset.get("id"))
                results["dify"] = {"ok": True, "dataset_id": dataset.get("id"),
                                   "mode": "pipeline", "start_node_id": node_id}
            except DifyError as exc:
                results["dify"] = {"ok": False, "error": str(exc)}
        else:
            results["dify"] = {"ok": True, "dataset_id": dataset.get("id"),
                               "mode": "general" if is_dify else "ragflow"}
    except DifyError as exc:
        results["dify"] = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        results["dify"] = {"ok": False, "error": str(exc)}
    finally:
        backend.close()

    results["dws"] = check_dws()
    results["ok"] = bool(results.get("dingtalk", {}).get("ok")
                         and results.get("dify", {}).get("ok"))
    return results


@router.post("/sources/test",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def test_source_draft(payload: SyncSourceTest, db=Depends(get_sync_db)):
    """保存前测试表单中选定的钉钉与目标知识库连接。"""
    return _test_source_connection(payload.dify_dataset_name, db, payload.dify_dataset_id,
                                   payload.backend_type)


@router.post("/sources/{source_id}/test",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def test_source(source_id: int, db=Depends(get_sync_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    return _test_source_connection(source.dify_dataset_name, db, source.dify_dataset_id,
                                   source.backend_type)


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
    # 数据集 runtime 模式缓存：模式（general/rag_pipeline）基本不变，
    # 缓存 10 分钟，免去每次预演都调一次 Dify resolve_dataset
    cache_key = f"{source.backend_type or 'dify'}:{source.dify_dataset_id or source.dify_dataset_name}"
    now = time()
    cached_mode = _dataset_runtime_cache.get(cache_key)
    if cached_mode is not None and now - cached_mode[0] < 600:
        mode = cached_mode[1]
    else:
        backend = make_backend(source, db)
        try:
            dataset = backend.resolve_dataset(source.dify_dataset_id, source.dify_dataset_name)
            # 知识流水线（rag_pipeline）是 Dify 专属；RAGFlow 一律按普通库
            mode = dataset_runtime(dataset) if (source.backend_type or "dify") == "dify" else "general"
        except (DifyError, ValueError) as exc:
            raise HTTPException(502, str(exc)) from exc
        finally:
            backend.close()
        _dataset_runtime_cache[cache_key] = (now, mode)
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
            items.append({**item_base, "action": "新增", "doc": name, "note": "未同步过，本次将写入 Dify"})
        else:
            items.append({**item_base, "action": "更新", "doc": name,
                          "note": "上一轮已同步，本次将重新上传" if mapping.status == "synced"
                          else "上次同步失败，将重试"})
    if source.delete_policy == "sync":
        for node_id, mapping in mappings.items():
            if node_id not in remote_ids:
                items.append({"action": "删除", "doc": mapping.name,
                              "note": "钉钉侧已删除，将同步删除 Dify 文档"})
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
def retry_failure(failure_id: int, db=Depends(get_sync_db)):
    failure = db.get(SyncFailure, failure_id)
    if failure is None:
        raise HTTPException(status_code=404, detail="失败记录不存在")
    source_id = failure.source_id
    _executor.submit(run_sync, source_id, "manual")
    return {"ok": True, "message": "已触发重试"}


@router.post("/failures/retry-all",
             dependencies=[Depends(require_role("super_admin", "admin", "editor"))])
def retry_all_failures(db=Depends(get_sync_db)):
    rows = db.query(SyncFailure).all()
    if not rows:
        return {"ok": True, "message": "没有待重试的失败项"}
    source_ids = sorted({r.source_id for r in rows})
    for sid in source_ids:
        _executor.submit(run_sync, sid, "manual")
    return {"ok": True, "message": f"已触发 {len(source_ids)} 个同步源重试"}


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
