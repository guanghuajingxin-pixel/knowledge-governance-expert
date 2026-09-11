"""仅由 runtime 启动的同步子进程。"""
import os
import signal
import sys
import threading

from kb_common.config import get_settings
from kb_common.models import SyncRun, SyncSource
from .runtime import WORKER_LOCK, source_lock
from .sync_database import SyncSessionLocal


def main(run_id: int) -> None:
    # Supervisor 被热重载/终止后，worker 仍有独立硬截止时间，避免孤儿进程永久存活。
    timer = threading.Timer(get_settings().sync_run_timeout_seconds + 5,
                            lambda: os.killpg(os.getpgrp(), signal.SIGKILL))
    timer.daemon = True
    timer.start()
    try:
        with SyncSessionLocal() as db:
            run = db.get(SyncRun, run_id)
            if run is None or run.status != 'running':
                return
            with source_lock(run.source_id, WORKER_LOCK) as acquired:
                if not acquired:
                    raise RuntimeError('同步源已有执行进程')
                source = db.get(SyncSource, run.source_id)
                from .engine import SyncEngine
                SyncEngine(source).run(run.trigger, run_id=run.id)
    finally:
        timer.cancel()


if __name__ == '__main__':
    main(int(sys.argv[1]))
