"""同步队列：失败任务的任务级重试（单文档重处理，不整源重跑）。

与整源重试（/sync/failures/{id}/retry → run_sync）的区别：
- 只把这一个失败任务重新入队 pending，由批处理作业分批重新下载/上传
  （retry_count 累加）；
- 不产生新的 SyncRun，失败记录 run_id 为空。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from kb_common.models import SyncTask

from .sync_database import SyncSessionLocal

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def submit_task_retry(task_id: int) -> None:
    """提交到后台线程执行，接口立即返回。"""
    _executor.submit(retry_task, task_id)


def retry_task(task_id: int) -> dict:
    """重处理单个失败任务；返回 {ok, message}。

    重新入队 pending，由批处理作业分批消费（与批处理并发安全）。
    """
    with SyncSessionLocal() as db:
        task = db.get(SyncTask, task_id)
        if task is None:
            return {"ok": False, "message": "任务不存在"}
        if task.status != "failed":
            return {"ok": False, "message": "仅失败任务可重试"}
        if not task.node_id or task.source_id is None:
            return {"ok": False, "message": "任务缺少钉钉节点或同步源信息，无法重试"}
        task.status = "pending"
        task.started_at = None
        task.finished_at = None
        task.error = ""
        task.retry_count = (task.retry_count or 0) + 1
        db.commit()
    return {"ok": True, "message": "任务已重新入队，等待批处理分批同步"}
