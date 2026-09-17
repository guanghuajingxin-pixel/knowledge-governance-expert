"""结构化处理路由：解析任务 / 表结构映射 / 预览 / 一键写入。

知识加工 · 二级页【结构化处理】的后端：
  1. 上传文档 + 选择 MinerU 解析引擎（kit_v1 / cloud_v4）触发异步解析；
  2. 表结构 + JSON 字段映射设计（structured_schemas CRUD）；
  3. 数据预览（按映射把解析 JSON 填充成行）；
  4. 一键写入共享 PG 的 structured schema（动态建表 + 追加）。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, func

from kb_common.database import get_session, SessionLocal
from kb_common.models import StructuredTask, StructuredSchema, StructuredWriteLog, Setting
from kb_common.config import get_settings
from app.deps import get_current_user
from app.services import structured_engine as eng

router = APIRouter(prefix="/api/v1/structured", tags=["structured"])

# 进程内解析任务句柄（MVP：不依赖 celery；服务重启后未完成任务标记 failed）
_BG_TASKS: dict[str, asyncio.Task] = {}


async def _resolve_write_url(s) -> tuple[str, str]:
    """写入目标库连接串优先级：settings 表 > 环境变量/配置 > 系统 database_url。"""
    row = (await s.execute(select(Setting).where(Setting.key == "structured_db_url"))).scalar_one_or_none()
    if row and (row.value or "").strip():
        return row.value.strip(), "settings（系统配置页/接口）"
    env_val = (get_settings().structured_db_url or "").strip()
    if env_val:
        return env_val, "环境变量 STRUCTURED_DB_URL"
    return get_settings().database_url, "跟随系统数据库 DATABASE_URL"


def _task_brief(t: StructuredTask) -> dict:
    return {
        "id": str(t.id),
        "file_name": t.file_name,
        "file_ext": t.file_ext,
        "engine": t.engine,
        "tier": t.tier,
        "ocr_mode": t.ocr_mode,
        "status": t.status,
        "error": t.error,
        "block_count": len(t.content_json or []) if isinstance(t.content_json, list) else 0,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
    }


# ---------- 引擎可用性 ----------
@router.get("/engines")
async def engines(u=Depends(get_current_user)):
    s = get_settings()
    kit_base = (s.structured_kit_base_url or "").strip()
    return {
        "kit_v1": {"available": await eng.kit_v1_available(), "base_url": kit_base},
        "cloud_v4": {"available": bool((s.mineru_api_key or "").strip()), "base_url": s.mineru_api_url},
    }


# ---------- 解析任务 ----------
@router.post("/tasks")
async def create_task(
    file: UploadFile = File(...),
    engine: str = Form("kit_v1"),
    tier: str = Form("standard"),
    ocr_mode: str = Form("auto"),
    session=Depends(get_session),
    u=Depends(get_current_user),
):
    if engine not in ("kit_v1", "cloud_v4"):
        raise HTTPException(400, f"不支持的解析引擎: {engine}")
    if engine == "kit_v1" and not await eng.kit_v1_available():
        raise HTTPException(400, "本地 mineru-kit V1 服务不可达，请改选 MinerU 云 API 或先启动本地引擎")
    if engine == "cloud_v4" and not (get_settings().mineru_api_key or "").strip():
        raise HTTPException(400, "未配置 MINERU_API_KEY，无法使用 MinerU 云 API 通道")
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    name = file.filename or "unnamed"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    task = StructuredTask(
        file_name=name, file_ext=ext, engine=engine, tier=tier, ocr_mode=ocr_mode, status="pending",
    )
    session.add(task)
    await session.commit()
    task_id = task.id
    _BG_TASKS[str(task_id)] = asyncio.create_task(
        _run_parse(task_id, data, name, engine, tier, ocr_mode)
    )
    return {"id": str(task_id), "status": "pending"}


async def _run_parse(task_id: uuid.UUID, data: bytes, name: str, engine: str, tier: str, ocr_mode: str):
    async with SessionLocal() as s:
        task = await s.get(StructuredTask, task_id)
        if not task:
            return
        task.status = "parsing"
        await s.commit()
        try:
            if engine == "cloud_v4":
                res = await eng.parse_with_cloud_v4(data, name)
            else:
                res = await eng.parse_with_kit_v1(data, name, tier, ocr_mode)
            task.content_json = res["content"]
            task.markdown = res["markdown"]
            task.meta = res["meta"]
            task.status = "completed"
        except Exception as e:  # noqa: BLE001
            task.status = "failed"
            task.error = str(e)
        task.finished_at = datetime.now()
        await s.commit()
    _BG_TASKS.pop(str(task_id), None)


@router.get("/tasks")
async def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    session=Depends(get_session),
    u=Depends(get_current_user),
):
    rows = (await session.execute(
        select(StructuredTask).order_by(StructuredTask.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"items": [_task_brief(t) for t in rows]}


@router.get("/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, session=Depends(get_session), u=Depends(get_current_user)):
    t = await session.get(StructuredTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return _task_brief(t)


@router.get("/tasks/{task_id}/content")
async def get_task_content(task_id: uuid.UUID, session=Depends(get_session), u=Depends(get_current_user)):
    t = await session.get(StructuredTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return {
        "id": str(t.id),
        "file_name": t.file_name,
        "status": t.status,
        "content": t.content_json or [],
        "markdown": t.markdown or "",
        "meta": t.meta or {},
    }


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: uuid.UUID, session=Depends(get_session), u=Depends(get_current_user)):
    t = await session.get(StructuredTask, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    bg = _BG_TASKS.pop(str(task_id), None)
    if bg:
        bg.cancel()
    await session.delete(t)
    await session.commit()
    return {"ok": True}


# ---------- 表结构 + 映射设计 ----------
def _schema_brief(sc: StructuredSchema) -> dict:
    return {
        "id": str(sc.id),
        "name": sc.name,
        "target_table": sc.target_table,
        "row_source": sc.row_source,
        "columns": sc.columns or [],
        "description": sc.description or "",
        "updated_at": sc.updated_at.isoformat() if sc.updated_at else None,
    }


@router.get("/schemas")
async def list_schemas(session=Depends(get_session), u=Depends(get_current_user)):
    rows = (await session.execute(select(StructuredSchema).order_by(StructuredSchema.updated_at.desc()))).scalars().all()
    return {"items": [_schema_brief(x) for x in rows]}


@router.post("/schemas")
async def create_schema(payload: dict, session=Depends(get_session), u=Depends(get_current_user)):
    name = (payload.get("name") or "").strip()
    target = (payload.get("target_table") or "").strip()
    if not name:
        raise HTTPException(400, "请填写方案名称")
    try:
        target = eng.sanitize_ident(target, "表")
    except ValueError as e:
        raise HTTPException(400, str(e))
    exists = (await session.execute(select(StructuredSchema).where(StructuredSchema.name == name))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"方案名「{name}」已存在")
    sc = StructuredSchema(
        name=name,
        target_table=target,
        row_source=(payload.get("row_source") or "content").strip() or "content",
        columns=payload.get("columns") or [],
        description=payload.get("description") or "",
    )
    session.add(sc)
    await session.commit()
    return _schema_brief(sc)


@router.put("/schemas/{schema_id}")
async def update_schema(schema_id: uuid.UUID, payload: dict, session=Depends(get_session), u=Depends(get_current_user)):
    sc = await session.get(StructuredSchema, schema_id)
    if not sc:
        raise HTTPException(404, "方案不存在")
    if payload.get("name"):
        sc.name = payload["name"].strip()
    if payload.get("target_table"):
        try:
            sc.target_table = eng.sanitize_ident(payload["target_table"], "表")
        except ValueError as e:
            raise HTTPException(400, str(e))
    if payload.get("row_source") is not None:
        sc.row_source = payload["row_source"].strip() or "content"
    if payload.get("columns") is not None:
        sc.columns = payload["columns"]
    if payload.get("description") is not None:
        sc.description = payload["description"]
    sc.updated_at = datetime.now()
    await session.commit()
    return _schema_brief(sc)


@router.delete("/schemas/{schema_id}")
async def delete_schema(schema_id: uuid.UUID, session=Depends(get_session), u=Depends(get_current_user)):
    sc = await session.get(StructuredSchema, schema_id)
    if not sc:
        raise HTTPException(404, "方案不存在")
    await session.delete(sc)
    await session.commit()
    return {"ok": True}


# ---------- 预览 / 写入 ----------
async def _resolve_mapping(session, payload: dict) -> tuple[StructuredTask, str, list]:
    task_id = payload.get("task_id")
    if not task_id:
        raise HTTPException(400, "请先选择解析任务")
    task = await session.get(StructuredTask, uuid.UUID(str(task_id)))
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "completed":
        raise HTTPException(400, f"任务尚未完成（status={task.status}），无法预览/写入")
    schema_id = payload.get("schema_id")
    if schema_id:
        sc = await session.get(StructuredSchema, uuid.UUID(str(schema_id)))
        if not sc:
            raise HTTPException(404, "方案不存在")
        return task, sc.row_source, sc.columns or []
    # 内联映射（未保存的设计也可直接预览）
    return task, (payload.get("row_source") or "content"), payload.get("columns") or []


@router.post("/preview")
async def preview(
    payload: dict,
    limit: int = Query(50, ge=1, le=500),
    session=Depends(get_session),
    u=Depends(get_current_user),
):
    task, row_source, columns = await _resolve_mapping(session, payload)
    root = {"content": task.content_json or [], "markdown": task.markdown or "", **(task.meta or {})}
    ctx = {
        "file_name": task.file_name,
        "task_id": str(task.id),
        "engine": task.engine,
        "parsed_at": task.finished_at.isoformat() if task.finished_at else "",
    }
    rows, warnings = eng.build_rows(root, row_source, columns, ctx)
    cols = [c["name"] for c in columns if c.get("name")]
    return {
        "columns": cols,
        "rows": rows[:limit],
        "total": len(rows),
        "warnings": warnings,
    }


@router.post("/write")
async def write(payload: dict, session=Depends(get_session), u=Depends(get_current_user)):
    schema_id = payload.get("schema_id")
    if not schema_id:
        raise HTTPException(400, "写入需指定已保存的方案（schema_id）")
    task, row_source, columns = await _resolve_mapping(session, payload)
    sc = await session.get(StructuredSchema, uuid.UUID(str(schema_id)))
    root = {"content": task.content_json or [], "markdown": task.markdown or "", **(task.meta or {})}
    ctx = {
        "file_name": task.file_name,
        "task_id": str(task.id),
        "engine": task.engine,
        "parsed_at": task.finished_at.isoformat() if task.finished_at else "",
    }
    rows, warnings = eng.build_rows(root, row_source, columns, ctx)
    log = StructuredWriteLog(schema_id=sc.id, task_id=task.id, target_table=sc.target_table)
    try:
        if not rows:
            raise RuntimeError("映射未产出任何行，请检查行源与字段路径")
        write_url, _src = await _resolve_write_url(session)
        async with eng.write_session(write_url) as ws:
            await eng.ensure_table(ws, sc.target_table, columns)
            n = await eng.insert_rows(ws, sc.target_table, columns, rows, str(task.id))
        log.rows_written = n
        log.status = "success"
    except Exception as e:  # noqa: BLE001
        log.status = "failed"
        log.error = str(e)
        session.add(log)
        await session.commit()
        raise HTTPException(400, f"写入失败：{e}")
    session.add(log)
    await session.commit()
    return {"target_table": f"structured.{sc.target_table}", "rows_written": log.rows_written, "warnings": warnings}


@router.get("/write-logs")
async def write_logs(
    limit: int = Query(50, ge=1, le=200),
    session=Depends(get_session),
    u=Depends(get_current_user),
):
    rows = (await session.execute(
        select(StructuredWriteLog).order_by(StructuredWriteLog.created_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "schema_id": str(r.schema_id) if r.schema_id else None,
                "task_id": str(r.task_id) if r.task_id else None,
                "target_table": r.target_table,
                "rows_written": r.rows_written,
                "status": r.status,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/tables")
async def tables(session=Depends(get_session), u=Depends(get_current_user)):
    url, _src = await _resolve_write_url(session)
    async with eng.write_session(url) as ws:
        return {"items": await eng.list_structured_tables(ws)}


# ---------- 写入目标库配置 ----------
@router.get("/target")
async def target_info(session=Depends(get_session), u=Depends(get_current_user)):
    url, source = await _resolve_write_url(session)
    return {"url_masked": eng.mask_db_url(url), "source": source}


@router.post("/test-target")
async def test_target(payload: dict, session=Depends(get_session), u=Depends(get_current_user)):
    url = (payload.get("url") or "").strip()
    if not url:
        url, _src = await _resolve_write_url(session)
    return await eng.test_db_url(url)
