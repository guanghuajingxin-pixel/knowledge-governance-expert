"""APScheduler 定时任务管理（迁移自 DingDingKonwledgePipeline，简化为直接从 sync_sources 读 cron）。

每个同步源的 cron 字段直接作为定时表达式，不保留独立 jobs 表。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from kb_common.models import SyncSource

from .engine import run_sync
from .sync_database import SyncSessionLocal
from .runtime import recover_interrupted_runs

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    return _scheduler


def _execute_source(source_id: int) -> None:
    logger.info("定时同步开始 source_id=%s", source_id)
    try:
        summary = run_sync(source_id, trigger="schedule")
        logger.info("定时同步结束: %s", summary)
    except Exception as exc:  # noqa: BLE001
        logger.exception("定时任务执行异常 source_id=%s: %s", source_id, exc)


def _job_wrapper(source_id: int) -> None:
    _execute_source(source_id)


def reload_sync_jobs() -> int:
    """重新加载所有 enabled 同步源的 cron 任务。返回已注册任务数。"""
    scheduler = get_scheduler()
    if scheduler.running:
        for job in scheduler.get_jobs():
            if job.id.startswith("sync-source-"):
                job.remove()

    db = SyncSessionLocal()
    count = 0
    try:
        sources = db.query(SyncSource).filter(SyncSource.enabled.is_(True)).all()
        for source in sources:
            try:
                trigger = CronTrigger.from_crontab(source.cron, timezone="Asia/Shanghai")
                scheduler.add_job(
                    _job_wrapper,
                    trigger=trigger,
                    args=[source.id],
                    id=f"sync-source-{source.id}",
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=300,
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("同步源 %s cron 解析失败 (%s): %s", source.id, source.cron, exc)
    finally:
        db.close()
    return count


def start_sync_scheduler() -> int:
    """FastAPI 启动时调用：启动调度器并加载所有同步源任务。"""
    scheduler = get_scheduler()
    recover_interrupted_runs()
    scheduler.add_job(recover_interrupted_runs, 'interval', seconds=30,
                      id='sync-recover-interrupted', replace_existing=True, max_instances=1)
    if not scheduler.running:
        scheduler.start()
    count = reload_sync_jobs()
    logger.info("同步调度器已启动，已加载 %s 个任务", count)
    return count


def shutdown_sync_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
