"""APScheduler 定时任务管理"""
from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from ..config import settings
from ..database import SessionLocal
from ..models import SyncJob, SyncSource
from .alert import alert_sync_failure
from .sync_engine import run_sync

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    return _scheduler


def _execute_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(SyncJob, job_id)
        if job is None:
            return
        source_id = job.source_id
        if source_id is None:
            source_ids = [row[0] for row in db.query(SyncSource.id).filter(SyncSource.enabled.is_(True)).all()]
            source_name = "全部同步源"
        else:
            source_ids = [source_id]
            source = db.get(SyncSource, source_id)
            source_name = source.name if source else str(source_id)
        job.last_run_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

    logger.info(f"开始执行定时同步 job_id={job_id}")
    summaries = []
    for sid in source_ids:
        summary = run_sync(sid, trigger="schedule")
        summaries.append(summary)
        logger.info(f"定时同步结束: {summary}")
        alert_sync_failure(source_name, summary)
    if not summaries:
        logger.warning(f"定时任务 {job_id} 没有可执行的同步源")


def _job_wrapper(job_id: int) -> None:
    try:
        _execute_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"定时任务执行异常 job_id={job_id}: {exc}")


def reload_jobs() -> int:
    scheduler = get_scheduler()
    if scheduler.running:
        for job in scheduler.get_jobs():
            if job.id.startswith("job-"):
                job.remove()

    db = SessionLocal()
    count = 0
    try:
        jobs = db.query(SyncJob).join(SyncSource).filter(
            SyncJob.enabled.is_(True), SyncSource.enabled.is_(True)
        ).all()
        for job in jobs:
            try:
                trigger = CronTrigger.from_crontab(job.cron, timezone="Asia/Shanghai")
                scheduler.add_job(
                    _job_wrapper,
                    trigger=trigger,
                    args=[job.id],
                    id=f"job-{job.id}",
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=300,
                )
                job.next_run_at = scheduler.get_job(f"job-{job.id}").next_run_time
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"任务 {job.name} cron 解析失败: {exc}")
        db.commit()
    finally:
        db.close()
    return count


def start_scheduler() -> BackgroundScheduler:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    reload_jobs()
    logger.info(f"定时调度器已启动，已加载 {len(scheduler.get_jobs())} 个任务")
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
