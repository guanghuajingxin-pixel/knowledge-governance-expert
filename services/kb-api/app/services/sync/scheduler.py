"""同步调度（XXL-Job 批处理 tick + 中断收编）。

职责划分：
- 定时编目已取消：自动同步由钉钉知识库变更事件驱动（event_listener.py），
  手动同步（上传文档/立即同步）进程内直跑编目；
- XXL-Job 仅保留全局批处理作业（syncBatch tick：分批消费编目预建的任务队列）；
- 中断运行收编扫描（超时/崩溃孤儿 run）为独立线程，与调度中心无关。

启动行为（fail-soft）：
- XXL_JOB_ENABLED=true 时 admin 不可达 → 跳过调度、降级线程消费批处理，启动告警；
- XXL_JOB_ENABLED=false → 调度中心整体不用，批处理由进程内降级线程消费。
- 启动时清理历史遗留的 syncSource 定时作业（定时编目时代的存量）。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kb_common.config import get_settings
from kb_common.models import SyncSource

from .runtime import recover_interrupted_runs
from .sync_database import SyncSessionLocal
from .xxljob_admin import XxlJobAdminClient, XxlJobAdminError, crontab_to_quartz
from .xxljob_executor import XxlJobExecutor, detect_ip

logger = logging.getLogger(__name__)

# 调度中心未启用时的进程内直跑通道（仅 XXL_JOB_ENABLED=false 的开发/降级场景）
_direct_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sync-direct")

_admin: XxlJobAdminClient | None = None
_executor: XxlJobExecutor | None = None
_group_id: int | None = None
_recovery_stop = threading.Event()
_recovery_thread: threading.Thread | None = None


def get_admin_client() -> XxlJobAdminClient:
    global _admin
    if _admin is None:
        s = get_settings()
        _admin = XxlJobAdminClient(s.xxl_job_admin_url, s.xxl_job_admin_user,
                                   s.xxl_job_admin_password, s.xxl_job_access_token)
    return _admin


def _ensure_group() -> int:
    global _group_id
    if _group_id is None:
        s = get_settings()
        _group_id = get_admin_client().ensure_group(
            s.xxl_job_executor_appname, "知识治理专家同步执行器")
    return _group_id


def _handle_sync_batch(param: str, job_log) -> tuple[int, str]:
    """xxl-job handler：全局批处理 tick（library 编目任务分批消费，param 未用）。"""
    from .batch import run_sync_batch_tick
    return run_sync_batch_tick(job_log)


def cleanup_source_jobs(admin: XxlJobAdminClient) -> int:
    """清理定时编目时代遗留的 syncSource 作业：持久化 ID + 孤儿扫描，幂等 best effort。"""
    removed = 0
    with SyncSessionLocal() as db:
        stale = db.query(SyncSource).filter(SyncSource.xxl_job_id.isnot(None)).all()
        for source in stale:
            job_id = source.xxl_job_id
            source.xxl_job_id = None
            if job_id:
                try:
                    admin.remove_job(job_id)
                    removed += 1
                except XxlJobAdminError as exc:
                    logger.warning("清理同步源 %s 的遗留作业 %s 失败: %s", source.id, job_id, exc)
        db.commit()
    # 补扫孤儿作业（xxl_job_id 未落库但调度中心仍存在的 syncSource 作业）。
    # 加单次上限：删除接口版本不匹配等异常场景下若作业始终删不掉，无限 while
    # 会以极高频率轰炸 admin（实测 90 次/秒打满 Tomcat 线程，拖死其它接口）；
    # 剩余孤儿下次启动继续清理。
    for _ in range(100):
        row = admin.find_job_by_handler("syncSource")
        if row is None:
            break
        try:
            admin.remove_job(int(row["id"]))
            removed += 1
        except XxlJobAdminError as exc:
            logger.warning("清理遗留 syncSource 作业 %s 失败: %s", row.get("id"), exc)
            break
    else:
        logger.warning("遗留 syncSource 作业清理达单次上限 100 个，其余下次启动继续")
    if removed:
        logger.info("已清理定时编目遗留的 syncSource 作业 %s 个", removed)
    return removed


def _batch_schedule_conf() -> str:
    """批处理调度表达式：兼容 5 段 crontab（自动转 Quartz）与 Quartz 6 段（含秒位）。"""
    raw = (get_settings().sync_batch_cron or "").strip()
    if len(raw.split()) == 5:
        return crontab_to_quartz(raw)
    return raw


def _batch_job_spec(group_id: int) -> dict:
    return {
        "jobGroup": group_id,
        "jobDesc": "知识同步批处理（全局）",
        "author": "kge",
        "alarmEmail": "",
        "scheduleType": "CRON",
        "scheduleConf": _batch_schedule_conf(),
        "glueType": "BEAN",
        "executorHandler": "syncBatch",
        "executorParam": "",
        "executorRouteStrategy": "FIRST",
        "childJobId": "",
        "misfireStrategy": "DO_NOTHING",
        # 单批可能超过 tick 间隔（大文件下载/解析提交）：丢弃堆积触发，靠 idleBeat 回报 busy
        "executorBlockStrategy": "DISCARD_LATER",
        "executorTimeout": 0,
        "executorFailRetryCount": 0,
        "glueRemark": "GLUE代码初始化描述",
    }


_batch_job_id: int | None = None


def _apply_batch_job(admin: XxlJobAdminClient, group_id: int) -> int | None:
    """幂等注册/启动全局批处理作业（按 executorHandler 查找，作业 ID 不落库）。"""
    global _batch_job_id
    spec = _batch_job_spec(group_id)
    try:
        if _batch_job_id:
            try:
                admin.update_job({**spec, "id": _batch_job_id})
                admin.start_job(_batch_job_id)
                return _batch_job_id
            except XxlJobAdminError:
                logger.warning("批处理作业 %s 更新失败，按 handler 重新查找", _batch_job_id)
                _batch_job_id = None
        row = admin.find_job_by_handler("syncBatch")
        if row is not None:
            _batch_job_id = int(row["id"])
            admin.update_job({**spec, "id": _batch_job_id})
        else:
            _batch_job_id = admin.add_job(spec)
        admin.start_job(_batch_job_id)
        return _batch_job_id
    except XxlJobAdminError as exc:
        logger.error("批处理作业注册失败: %s", exc)
        _batch_job_id = None
        return None


def ensure_batch_job_running() -> int | None:
    """确保批处理作业已在 admin 注册并启动（编目触发批处理前调用）。"""
    if not get_settings().xxl_job_enabled:
        return None
    return _apply_batch_job(get_admin_client(), _ensure_group())


def trigger_batch_once() -> None:
    """立即触发一轮批处理（编目完成后调用，不等下一个 tick；best effort）。"""
    if not get_settings().xxl_job_enabled:
        from .batch import run_sync_batch_tick
        _direct_executor.submit(run_sync_batch_tick)
        return
    job_id = _batch_job_id or ensure_batch_job_running()
    if job_id:
        get_admin_client().trigger_job(job_id)


def trigger_source_sync(source_id: int, operator: str = "") -> dict:
    """「确认并开始同步」/立即同步：进程内直跑编目（run_catalog）。

    定时编目已取消，不再经 XXL-Job admin 触发；编目内部会接着触发批处理
    （ensure_batch_job_running + trigger_batch_once / 进程内降级线程），
    任务/文档进同步队列由批处理分批消费，进度在同步队列查看。
    """
    from .catalog import run_catalog
    _direct_executor.submit(run_catalog, source_id, "manual", operator)
    return {"via": "direct",
            "message": "同步任务已提交，进度可在同步队列查看"}


def trigger_first_sync(source_id: int, operator: str = "") -> dict:
    """同步源创建后的首次同步（与手动同步同一通道）。"""
    return trigger_source_sync(source_id, operator)


def remove_source_job(job_id: int | None) -> None:
    """删除同步源时清理调度中心遗留作业（定时编目时代存量，best effort）。"""
    if not job_id or not get_settings().xxl_job_enabled:
        return
    try:
        get_admin_client().remove_job(job_id)
    except XxlJobAdminError as exc:
        logger.warning("删除 XXL-Job 作业 %s 失败（请在控制台手工清理）: %s", job_id, exc)


def _recovery_loop() -> None:
    while not _recovery_stop.wait(30):
        try:
            recover_interrupted_runs()
        except Exception:  # noqa: BLE001
            logger.exception("中断运行收编扫描失败")


def _start_recovery_thread() -> None:
    global _recovery_thread
    if _recovery_thread is not None and _recovery_thread.is_alive():
        return
    _recovery_stop.clear()
    _recovery_thread = threading.Thread(target=_recovery_loop,
                                        name="sync-recover-interrupted", daemon=True)
    _recovery_thread.start()


# 降级批处理轮询：XXL_JOB_ENABLED=false / admin 不可达时由进程内线程兜底消费队列，
# 间隔与默认批处理 cron（每 30s）对齐。
_BATCH_FALLBACK_INTERVAL_SECONDS = 30
_batch_fallback_stop = threading.Event()
_batch_fallback_thread: threading.Thread | None = None


def _batch_fallback_loop() -> None:
    from .batch import run_sync_batch_tick
    while not _batch_fallback_stop.wait(_BATCH_FALLBACK_INTERVAL_SECONDS):
        try:
            run_sync_batch_tick()
        except Exception:  # noqa: BLE001
            logger.exception("降级批处理 tick 失败")


def _start_batch_fallback_thread() -> None:
    global _batch_fallback_thread
    if _batch_fallback_thread is not None and _batch_fallback_thread.is_alive():
        return
    _batch_fallback_stop.clear()
    _batch_fallback_thread = threading.Thread(target=_batch_fallback_loop,
                                              name="sync-batch-fallback", daemon=True)
    _batch_fallback_thread.start()


def start_sync_scheduler() -> int:
    """FastAPI 启动时调用。

    XXL-Job admin 不可达时**降级**（记录错误、跳过 executor 启动），
    绝不抛异常——lifespan 抛异常会直接杀死整个 kb-api（BGE-M3/搜索/问答全挂），
    且 reloader 模式下 worker 退出后端口仍在监听但无人 accept，所有请求挂死超时。
    调度缺席时批处理由进程内降级线程消费；自动同步由事件监听驱动，不受影响。
    """
    s = get_settings()
    _start_recovery_thread()
    if not s.xxl_job_enabled:
        logger.warning("XXL-Job 调度已禁用（XXL_JOB_ENABLED=false）："
                       "批处理 tick 由进程内降级线程消费；自动同步（事件监听）/手动同步不受影响")
        _start_batch_fallback_thread()
        return 0
    admin = get_admin_client()
    try:
        admin.ping()
    except Exception as exc:  # noqa: BLE001 — 调度器缺席不能拖死 API 服务
        logger.error("XXL-Job admin 不可达（%s），本次启动跳过定时调度："
                     "批处理由进程内降级线程消费；自动同步（事件监听）/手动同步不受影响。"
                     "恢复 admin 后重启 kb-api 即可恢复调度", exc)
        _start_batch_fallback_thread()
        return 0
    global _executor
    ip = s.xxl_job_executor_ip or detect_ip(s.xxl_job_admin_url)
    log_path = (Path(s.xxl_job_executor_log_path) if s.xxl_job_executor_log_path
                else Path(__file__).resolve().parents[3] / "data" / "xxljob-log")
    _executor = XxlJobExecutor(s.xxl_job_admin_url, s.xxl_job_access_token,
                               s.xxl_job_executor_appname, ip, s.xxl_job_executor_port,
                               log_path)
    _executor.start({"syncBatch": _handle_sync_batch})
    # 定时编目已取消：仅注册批处理作业，并清理定时编目时代的遗留 syncSource 作业
    try:
        cleanup_source_jobs(admin)
    except Exception as exc:  # noqa: BLE001 — 遗留作业清理失败不影响启动
        logger.warning("遗留 syncSource 作业清理失败（可稍后在调度控制台手工清理）: %s", exc)
    group_id = _ensure_group()
    _apply_batch_job(admin, group_id)
    logger.info("XXL-Job 调度已启动：执行器 http://%s:%s，批处理作业已注册"
                "（定时编目已取消，自动同步由知识库变更事件驱动）", ip, s.xxl_job_executor_port)
    return 1


def shutdown_sync_scheduler() -> None:
    _recovery_stop.set()
    _batch_fallback_stop.set()
    global _executor
    if _executor is not None:
        _executor.stop()
        _executor = None
