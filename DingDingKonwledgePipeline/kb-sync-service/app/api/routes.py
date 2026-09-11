"""FastAPI 路由"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AppSetting, DocumentMapping, SyncFailure, SyncJob, SyncLog, SyncRun, SyncSource
from ..schemas import (
    FailureOut, JobCreate, JobOut, JobUpdate, LoginRequest, LoginResponse,
    LogOut, RunOut, SettingsOut, SettingsUpdate, SourceCreate, SourceOut,
    SourceUpdate,
)
from ..services.dify_client import DifyClient, DifyError
from ..services.dingtalk_client import DingTalkClient, DingTalkError
from ..services.export_service import check_dws
from ..services.scheduler import reload_jobs
from ..services.sync_engine import run_sync

router = APIRouter(prefix="/api")
_executor = ThreadPoolExecutor(max_workers=4)






# ---------- 认证 ----------
def _make_token(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}:{password}:{settings.secret_key}".encode()).hexdigest()


def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = _make_token(settings.admin_username, settings.admin_password)
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="未认证或 token 无效")


@router.get("/dingtalk/workspaces", dependencies=[Depends(require_auth)])
def dingtalk_workspaces():
    dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                        settings.dingtalk_operator_id)
    try:
        return dt.list_workspaces()
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"获取知识库失败: {exc}")
    finally:
        dt.close()

@router.get("/dingtalk/nodes", dependencies=[Depends(require_auth)])
def dingtalk_nodes(parent_node_id: str = Query(...), max_results: int = Query(50, le=100)):
    dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                        settings.dingtalk_operator_id)
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
@router.get("/dingtalk/tree", dependencies=[Depends(require_auth)])
def dingtalk_tree(root_node_id: str = Query(...), depth: int = Query(5, le=20)):
    dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                        settings.dingtalk_operator_id)
    try:
        return dt.build_tree(root_node_id, max_depth=depth,
                             max_results=settings.max_results_per_page)
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"获取目录树失败: {exc}")
    finally:
        dt.close()

@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return LoginResponse(token=_make_token(payload.username, payload.password))




# ---------- 工作台 ----------
@router.get("/dashboard", dependencies=[Depends(require_auth)])
def dashboard(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)
    source_count = db.query(func.count(SyncSource.id)).scalar() or 0
    job_count = db.query(func.count(SyncJob.id)).scalar() or 0
    enabled_job_count = (db.query(func.count(SyncJob.id))
                         .filter(SyncJob.enabled.is_(True)).scalar() or 0)
    run_count_today = (db.query(func.count(SyncRun.id))
                       .filter(SyncRun.started_at >= day_start).scalar() or 0)
    failed_today = (db.query(func.count(SyncRun.id))
                    .filter(SyncRun.started_at >= day_start,
                            SyncRun.status == "failed").scalar() or 0)
    doc_count = db.query(func.count(DocumentMapping.id)).scalar() or 0
    last_run = db.query(SyncRun).order_by(SyncRun.started_at.desc()).first()
    return {
        "source_count": source_count,
        "job_count": job_count,
        "enabled_job_count": enabled_job_count,
        "doc_count": doc_count,
        "run_count_today": run_count_today,
        "failed_today": failed_today,
        "last_run": RunOut.model_validate(last_run).model_dump() if last_run else None,
    }




# ---------- 同步源 ----------
@router.get("/sources", response_model=list[SourceOut], dependencies=[Depends(require_auth)])
def list_sources(db: Session = Depends(get_db)):
    return db.query(SyncSource).order_by(SyncSource.id.desc()).all()


@router.post("/sources", response_model=SourceOut, dependencies=[Depends(require_auth)])
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["dify_dataset_name"] = (data.get("dify_dataset_name") or "").strip() \
        or (data.get("start_dir") or "").strip() or (data.get("name") or "").strip()
    source = SyncSource(**data)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/sources/{source_id}", response_model=SourceOut, dependencies=[Depends(require_auth)])
def get_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    return source


@router.put("/sources/{source_id}", response_model=SourceOut, dependencies=[Depends(require_auth)])
def update_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "dify_dataset_name" in updates and not (updates.get("dify_dataset_name") or "").strip():
        updates["dify_dataset_name"] = (updates.get("start_dir") or source.start_dir or "").strip() \
            or (updates.get("name") or source.name or "").strip()
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    reload_jobs()
    return source


@router.delete("/sources/{source_id}", dependencies=[Depends(require_auth)])
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    db.delete(source)
    db.commit()
    reload_jobs()
    return {"ok": True}


@router.post("/sources/{source_id}/test", dependencies=[Depends(require_auth)])
def test_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")

    results: dict[str, Any] = {}
    dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                        settings.dingtalk_operator_id)
    try:
        results["dingtalk"] = dt.test_connection()
    except DingTalkError as exc:
        results["dingtalk"] = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        results["dingtalk"] = {"ok": False, "error": str(exc)}
    finally:
        dt.close()

    dify = DifyClient(settings.dify_base_url, settings.dify_dataset_api_key)
    try:
        data = dify.list_datasets(page=1, limit=1)
        results["dify"] = {"ok": True, "dataset_count": data.get("total", len(data.get("data", [])))}
    except DifyError as exc:
        results["dify"] = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        results["dify"] = {"ok": False, "error": str(exc)}
    finally:
        dify.close()

    results["dws"] = check_dws(settings.dws_bin)
    results["ok"] = all((results.get("dingtalk", {}).get("ok"),
                         results.get("dify", {}).get("ok")))
    return results


@router.post("/sources/{source_id}/sync", dependencies=[Depends(require_auth)])
def sync_source_now(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    _executor.submit(run_sync, source_id, "manual")
    return {"ok": True, "message": "同步已提交，稍后可在运行监控查看结果"}


@router.get("/sources/{source_id}/stats", dependencies=[Depends(require_auth)])
def source_stats(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    doc_count = db.query(func.count(DocumentMapping.id)).filter(DocumentMapping.source_id == source_id).scalar() or 0
    last_run = db.query(SyncRun).filter(SyncRun.source_id == source_id).order_by(SyncRun.started_at.desc()).first()
    return {"doc_count": doc_count, "last_run": RunOut.model_validate(last_run).model_dump() if last_run else None}


def _node_meta_hash(node: dict) -> str:
    ts_keys = ("updatedAt", "updateTime", "modifiedAt", "modifiedTime")
    stamps = {k: node.get(k) for k in ts_keys if node.get(k)}
    if not stamps:
        return ""
    raw = json.dumps({**{"name": node.get("name", ""), "category": node.get("category", "")}, **stamps},
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


@router.post("/sources/{source_id}/preview", dependencies=[Depends(require_auth)])
def preview_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(SyncSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="同步源不存在")
    dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                        settings.dingtalk_operator_id)
    try:
        nodes = dt.walk_tree(source.root_node_id, settings.max_depth, settings.max_results_per_page)
    except DingTalkError as exc:
        raise HTTPException(status_code=502, detail=f"钉钉遍历失败: {exc}")
    finally:
        dt.close()

    mappings = {m.node_id: m for m in db.query(DocumentMapping).filter_by(source_id=source_id).all()}
    skip_exts = settings.skip_ext_list
    items: list[dict] = []
    remote_ids: set[str] = set()
    for node in nodes:
        node_id = node.get("nodeId", "")
        remote_ids.add(node_id)
        name = node.get("name", node_id)
        ext = FsPath(name).suffix.lower()
        if ext in skip_exts:
            items.append({"action": "跳过", "doc": name, "note": "扩展名在跳过列表，不处理"})
            continue
        mapping = mappings.get(node_id)
        if mapping is None:
            items.append({"action": "新增", "doc": name, "note": "预演 · 未写入 Dify"})
        elif mapping.status != "synced":
            items.append({"action": "更新", "doc": name, "note": "上次同步失败，将重试"})
        elif _node_meta_hash(node) and mapping.meta_hash != _node_meta_hash(node):
            items.append({"action": "更新", "doc": name, "note": "节点内容已变化"})
    if source.delete_policy == "sync":
        for node_id, mapping in mappings.items():
            if node_id not in remote_ids:
                items.append({"action": "删除", "doc": mapping.name, "note": "钉钉侧已删除，将同步删除 Dify 文档"})
    return items


@router.post("/failures/{failure_id}/retry", dependencies=[Depends(require_auth)])
def retry_failure(failure_id: int, db: Session = Depends(get_db)):
    failure = db.get(SyncFailure, failure_id)
    if failure is None:
        raise HTTPException(status_code=404, detail="失败记录不存在")
    source_id = failure.source_id
    db.delete(failure)
    db.commit()
    _executor.submit(run_sync, source_id, "manual")
    return {"ok": True, "message": "已触发重试"}


@router.post("/failures/retry-all", dependencies=[Depends(require_auth)])
def retry_all_failures(db: Session = Depends(get_db)):
    rows = db.query(SyncFailure).all()
    if not rows:
        return {"ok": True, "message": "没有待重试的失败项"}
    source_ids = sorted({r.source_id for r in rows})
    for r in rows:
        db.delete(r)
    db.commit()
    for sid in source_ids:
        _executor.submit(run_sync, sid, "manual")
    return {"ok": True, "message": f"已触发 {len(source_ids)} 个同步源重试"}




# ---------- 定时任务 ----------
@router.get("/jobs", response_model=list[JobOut], dependencies=[Depends(require_auth)])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(SyncJob).order_by(SyncJob.id.desc()).all()


@router.post("/jobs", response_model=JobOut, dependencies=[Depends(require_auth)])
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    source_id = None if payload.source_id in (None, 0) else payload.source_id
    if source_id is not None and db.get(SyncSource, source_id) is None:
        raise HTTPException(status_code=400, detail="同步源不存在")
    job = SyncJob(**{**payload.model_dump(), "source_id": source_id})
    db.add(job)
    db.commit()
    db.refresh(job)
    reload_jobs()
    return job


@router.put("/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_auth)])
def update_job(job_id: int, payload: JobUpdate, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if payload.source_id is not None and payload.source_id != 0 and db.get(SyncSource, payload.source_id) is None:
        raise HTTPException(status_code=400, detail="同步源不存在")
    data = payload.model_dump(exclude_unset=True)
    if "source_id" in data:
        data["source_id"] = None if data["source_id"] in (None, 0) else data["source_id"]
    for key, value in data.items():
        setattr(job, key, value)
    db.commit()
    db.refresh(job)
    reload_jobs()
    return job


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_auth)])
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    db.delete(job)
    db.commit()
    reload_jobs()
    return {"ok": True}


@router.post("/jobs/{job_id}/run", dependencies=[Depends(require_auth)])
def run_job_now(job_id: int, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    _executor.submit(run_sync, job.source_id, "manual")
    return {"ok": True, "message": "同步已提交"}


@router.post("/jobs/{job_id}/toggle", response_model=JobOut, dependencies=[Depends(require_auth)])
def toggle_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    job.enabled = not job.enabled
    db.commit()
    db.refresh(job)
    reload_jobs()
    return job




# ---------- 运行监控 / 日志 / 失败 ----------
@router.get("/runs", response_model=list[RunOut], dependencies=[Depends(require_auth)])
def list_runs(source_id: int | None = None, limit: int = Query(20, le=200),
              offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(SyncRun)
    if source_id is not None:
        query = query.filter(SyncRun.source_id == source_id)
    return query.order_by(SyncRun.started_at.desc()).offset(offset).limit(limit).all()


@router.get("/runs/{run_id}", dependencies=[Depends(require_auth)])
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    failures = db.query(SyncFailure).filter_by(run_id=run_id).order_by(SyncFailure.id.desc()).all()
    logs = db.query(SyncLog).filter_by(run_id=run_id).order_by(SyncLog.id.asc()).all()
    return {
        "run": RunOut.model_validate(run).model_dump(),
        "failures": [FailureOut.model_validate(f).model_dump() for f in failures],
        "logs": [LogOut.model_validate(l).model_dump() for l in logs],
    }


@router.get("/failures", response_model=list[FailureOut], dependencies=[Depends(require_auth)])
def list_failures(run_id: int | None = None, limit: int = Query(50, le=200),
                  offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(SyncFailure)
    if run_id is not None:
        query = query.filter(SyncFailure.run_id == run_id)
    return query.order_by(SyncFailure.id.desc()).offset(offset).limit(limit).all()


@router.get("/logs", response_model=list[LogOut], dependencies=[Depends(require_auth)])
def list_logs(run_id: int | None = None, limit: int = Query(100, le=500),
              offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(SyncLog)
    if run_id is not None:
        query = query.filter(SyncLog.run_id == run_id)
    return query.order_by(SyncLog.id.desc()).offset(offset).limit(limit).all()




# ---------- 设置 ----------
_SETTING_KEYS = {
    "dingtalk_webhook", "alert_failure_threshold", "default_delete_policy",
    "export_format", "max_depth", "dify_wait_indexing", "dingtalk_operator_id",
}


def _effective_settings(db: Session) -> dict[str, Any]:
    values = {
        "dingtalk_webhook": settings.dingtalk_webhook,
        "alert_failure_threshold": settings.alert_failure_threshold,
        "default_delete_policy": settings.default_delete_policy,
        "export_format": settings.export_format,
        "max_depth": settings.max_depth,
        "dify_wait_indexing": settings.dify_wait_indexing,
        "dingtalk_operator_id": settings.dingtalk_operator_id,
    }
    for row in db.query(AppSetting).filter(AppSetting.key.in_(_SETTING_KEYS)).all():
        values[row.key] = _coerce(row.value, values[row.key])
    return values


def _coerce(value: str, example: Any) -> Any:
    if isinstance(example, bool):
        return value.lower() in ("1", "true", "yes", "on")
    if isinstance(example, int):
        try:
            return int(value)
        except ValueError:
            return example
    return value


@router.get("/settings", response_model=SettingsOut, dependencies=[Depends(require_auth)])
def get_settings(db: Session = Depends(get_db)):
    return _effective_settings(db)


@router.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_auth)])
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    updates = payload.model_dump(exclude_unset=True)
    if "dify_dataset_name" in updates and not (updates.get("dify_dataset_name") or "").strip():
        updates["dify_dataset_name"] = (updates.get("start_dir") or source.start_dir or "").strip() \
            or (updates.get("name") or source.name or "").strip()
    for key, value in updates.items():
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=str(value))
            db.add(row)
        else:
            row.value = str(value)
        setattr(settings, key, value)
    db.commit()
    return _effective_settings(db)
