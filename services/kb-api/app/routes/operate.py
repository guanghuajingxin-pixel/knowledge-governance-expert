"""运营看板路由。

统计与持久化策略（流水表 operate_metric_records）：
- 知识存储总量 / 知识数量（含分布）/ 热门知识 Top20：每日 0 点定时统计（kb-api 内置调度器），
  或点「刷新」手动触发；每个指标统计完成即写入一条流水，展示时取各指标最新一条记录。
- 服务重启后从流水表恢复最新数据；若当天尚无记录（如 0 点时服务宕机）则自动补统计。
- 知识召回数 / 调用量：待知识采集流程打通、Dify 文档关联钉钉文档 ID 后统计（前端显示"即将发布"）。
"""
import asyncio
import logging
import time
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session, SessionLocal
from app.deps import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operate", tags=["operate"])

# ===== 配置 =====
_HOT_CATEGORIES = {"DOCUMENT", "ALIDOC"}   # 热门统计只算知识文档（上传文档 + 在线文档）
_RECORD_RETENTION_DAYS = 180               # 流水保留天数

# 遍历原始数据缓存（供热门扫描取候选清单；TTL 1 小时）
_stats_cache: dict = {"data": None, "expire_at": 0.0, "error": None, "walk_info": None}
# 热门扫描实时进度（进行中时供接口读取；完成后快照进 _snapshot 并落库）
_hot_cache: dict = {"scores": {}, "scanned": 0, "total": 0}
# 各指标最新统计结果（内存镜像 = 流水表最新记录；重启后由 _hydrate_snapshot 恢复）
_snapshot: dict = {"storage": None, "knowledge_count": None, "hot_docs": None, "loaded": False}
# 全量统计任务状态（phase: storage → walk → hot）
_job: dict = {"running": False, "phase": None}
_scheduler_started = False


def _gb(b: int) -> str:
    return f"{b / 1024 / 1024 / 1024:.2f}"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return date.today().isoformat()


# ===== 流水表读写 =====
async def _save_metric_record(metric_key: str, value: dict, trigger: str) -> None:
    """写入一条指标流水，并清理过期流水。"""
    from kb_common.models import OperateMetricRecord
    value = {**value, "metric_date": _today()}
    async with SessionLocal() as s:
        s.add(OperateMetricRecord(metric_key=metric_key, metric_date=date.today(),
                                  value=value, trigger=trigger))
        cutoff = date.today() - timedelta(days=_RECORD_RETENTION_DAYS)
        await s.execute(delete(OperateMetricRecord).where(OperateMetricRecord.metric_date < cutoff))
        await s.commit()


async def _load_latest_record(metric_key: str) -> dict | None:
    """取某指标最新一条流水。"""
    from kb_common.models import OperateMetricRecord
    async with SessionLocal() as s:
        row = (await s.execute(
            select(OperateMetricRecord)
            .where(OperateMetricRecord.metric_key == metric_key)
            .order_by(OperateMetricRecord.id.desc())
            .limit(1))).scalar_one_or_none()
        return row.value if row else None


async def _hydrate_snapshot() -> None:
    """服务启动后首次访问时，从流水表恢复各指标最新记录到内存快照。"""
    if _snapshot["loaded"]:
        return
    _snapshot["loaded"] = True
    for key in ("storage", "knowledge_count", "hot_docs"):
        try:
            val = await _load_latest_record(key)
        except Exception as e:
            logger.warning("读取运营指标流水失败(%s): %s", key, e)
            val = None
        if val:
            _snapshot[key] = val
    logger.info("运营指标快照已从流水表恢复：%s",
                [k for k in ("storage", "knowledge_count", "hot_docs") if _snapshot.get(k)])


def _is_stale() -> bool:
    """任一指标今天还没有统计记录 → 视为过期（需要重新统计）。"""
    for key in ("storage", "knowledge_count", "hot_docs"):
        v = _snapshot.get(key)
        if not v or v.get("metric_date") != _today():
            return True
    return False


# ===== 全量统计任务 =====
def _start_job(trigger: str) -> bool:
    """启动全量统计（已有任务在跑则忽略）。"""
    if _job["running"]:
        return False
    _job["running"] = True
    _job["phase"] = "storage"
    asyncio.create_task(_run_full_stats(trigger))
    return True


async def _run_full_stats(trigger: str) -> None:
    """全量统计：存储总量 → 知识数量/分布（全量遍历）→ 热门 Top20，各完成即落库并更新快照。"""
    from kb_common.clients import dingtalk_client as dt
    try:
        await dt.sync_runtime_config()
        if not dt.is_configured():
            logger.info("钉钉未配置，跳过运营指标统计")
            return

        # ---- 1) 存储总量（企业存储 API → CLI 兜底，秒级） ----
        sv = {"value": None, "bytes": None, "fallback": False, "error": None}
        try:
            b = await dt.get_org_storage_used()
            sv["bytes"] = b
            sv["value"] = _gb(b)
        except Exception as e:
            sv["error"] = str(e)
            logger.warning("存储总量获取失败: %s", e)
        if sv["value"]:
            await _save_metric_record("storage", sv, trigger)
            _snapshot["storage"] = {**sv, "created_at": _now_str()}

        # ---- 2) 知识数量 + 企业分布（全量遍历，约 30 分钟） ----
        _job["phase"] = "walk"
        data = None
        try:
            data = await dt.get_all_workspaces_stats()
            _stats_cache["data"] = data
            _stats_cache["walk_info"] = dt.get_last_walk_info()
            _stats_cache["expire_at"] = time.time() + 3600
            _stats_cache["error"] = None
            logger.info("钉钉知识库遍历完成：%d 个知识库", len(data))
        except Exception as e:
            _stats_cache["error"] = str(e)
            logger.warning("钉钉知识库遍历失败: %s", e)

        if data:
            # 无存储权限时回退为上传文件大小累计（在线文档 size=0，偏小）
            if sv["error"] and not sv["value"]:
                fb_bytes = sum(w.get("total_size", 0) for w in data)
                sv.update(bytes=fb_bytes, value=_gb(fb_bytes), fallback=True)

            kc = {
                "value": sum(w.get("file_count", 0) for w in data),
                "month_new": _count_month_new(data),
                "distribution": [
                    {"name": w.get("name", "未命名"), "value": w.get("file_count", 0),
                     "workspace_id": w.get("workspace_id")}
                    for w in sorted(data, key=lambda x: x.get("file_count", 0), reverse=True)
                ],
            }
            wi = _stats_cache.get("walk_info") or {}
            if wi.get("failed_folders"):
                kc["partial"] = True
                kc["failed_folders"] = wi["failed_folders"]
            await _save_metric_record("knowledge_count", kc, trigger)
            _snapshot["knowledge_count"] = {**kc, "created_at": _now_str()}

        # 存储失败时：回退尝试后落库（记录 error 供前端提示；成功时前面已落过）
        if not sv["value"]:
            await _save_metric_record("storage", sv, trigger)
            _snapshot["storage"] = {**sv, "created_at": _now_str()}

        # ---- 3) 热门知识 Top20（逐文档统计，约 30 分钟） ----
        if data:
            _job["phase"] = "hot"
            await _scan_hot_docs(trigger)

        logger.info("运营指标全量统计完成（trigger=%s）", trigger)
    except Exception as e:
        logger.warning("运营指标全量统计失败: %s", e)
    finally:
        _job["running"] = False
        _job["phase"] = None


def _count_month_new(data: list[dict]) -> int:
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    n = 0
    for w in data:
        for f in w.get("files", []):
            mt = f.get("modified_time") or ""
            try:
                if datetime.strptime(mt[:19], "%Y-%m-%dT%H:%M:%S") >= month_start:
                    n += 1
            except Exception:
                pass
    return n


async def _scan_hot_docs(trigger: str) -> None:
    """并发调用 dws drive stats 逐文档统计访问/阅读数，完成后落库。"""
    from kb_common.clients import dingtalk_client as dt
    candidates = []
    for w in (_stats_cache["data"] or []):
        for f in w.get("files", []):
            if (f.get("category") or "") in _HOT_CATEGORIES and f.get("node_id"):
                candidates.append(f)
    _hot_cache["total"] = len(candidates)
    _hot_cache["scores"] = {}
    _hot_cache["scanned"] = 0
    sem = asyncio.Semaphore(3)

    async def worker(f: dict) -> None:
        async with sem:
            try:
                st = await dt.get_node_stats_via_cli(f["node_id"])
            except Exception:
                return  # 单节点失败跳过，不中断整体
            _hot_cache["scores"][f["node_id"]] = st
            _hot_cache["scanned"] += 1

    await asyncio.gather(*(worker(f) for f in candidates))
    hd: dict = {"items": _top_hot_docs(20), "total": _hot_cache["total"],
                "scanned": _hot_cache["scanned"]}
    if _hot_cache["scanned"] < _hot_cache["total"]:
        hd["partial"] = True
    await _save_metric_record("hot_docs", hd, trigger)
    _snapshot["hot_docs"] = {**hd, "created_at": _now_str()}
    logger.info("热门知识统计完成：%d/%d 个文档", _hot_cache["scanned"], _hot_cache["total"])


def _top_hot_docs(n: int = 20) -> list[dict]:
    """按访问次数（查看）倒序取 Top N，访问数相同按阅读数排序。"""
    ranked = []
    for w in (_stats_cache["data"] or []):
        for f in w.get("files", []):
            st = _hot_cache["scores"].get(f.get("node_id"))
            if st:
                ranked.append({
                    "node_id": f.get("node_id"),
                    "title": f.get("name", ""),
                    "workspace": w.get("name", "未命名"),
                    "url": f.get("url") or "",
                    "read_count": st.get("read_count", 0),
                    "count": st.get("visit_count", 0),
                })
    ranked.sort(key=lambda x: (x["count"], x["read_count"]), reverse=True)
    out = []
    for i, r in enumerate(ranked[:n], 1):
        r["rank"] = i
        out.append(r)
    return out


# ===== 每日 0 点定时调度 =====
async def _daily_scheduler() -> None:
    while True:
        now = datetime.now()
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=10, microsecond=0)
        await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
        logger.info("每日 0 点定时统计启动")
        _start_job("daily")


def start_operate_scheduler() -> None:
    """FastAPI 启动时调用：恢复快照 + 缺今日数据则补统计 + 注册每日 0 点任务。"""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    async def _bootstrap() -> None:
        await asyncio.sleep(3)  # 等 DB / 事件循环就绪
        try:
            await _hydrate_snapshot()
        except Exception as e:
            logger.warning("运营指标快照恢复失败: %s", e)
        if _is_stale():
            logger.info("运营指标缺少今日数据，启动补统计")
            _start_job("daily")

    asyncio.create_task(_bootstrap())
    asyncio.create_task(_daily_scheduler())


# ===== 接口 =====
@router.get("/overview")
async def overview(u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
                   s: AsyncSession = Depends(get_session)):
    """顶部核心指标：取流水表最新记录展示（内存快照镜像）。"""
    from kb_common.clients import dingtalk_client as dt
    await dt.sync_runtime_config()
    await _hydrate_snapshot()

    # 今天还没有数据（如 0 点服务重启错过定时任务）→ 兜底触发补统计
    if dt.is_configured() and _is_stale() and not _job["running"]:
        _start_job("daily")

    sv = _snapshot.get("storage") or {}
    kc = _snapshot.get("knowledge_count") or {}
    return {
        "storage": {
            "value": sv.get("value"), "unit": "GB", "month_new": "-", "mom": "-",
            "error": sv.get("error"), "fallback": sv.get("fallback", False),
            "loading": bool(dt.is_configured() and _job["running"] and not sv.get("value")),
            "updated_at": sv.get("created_at"),
        },
        "knowledge_count": {
            "value": kc.get("value"), "unit": "份", "month_new": kc.get("month_new"), "mom": "-",
            "partial": kc.get("partial"), "failed_folders": kc.get("failed_folders"),
            "loading": bool(dt.is_configured() and _job["running"] and kc.get("value") is None),
            "updated_at": kc.get("created_at"),
        },
        "dingtalk_configured": dt.is_configured(),
        "job": {"running": _job["running"], "phase": _job["phase"]},
    }


@router.get("/knowledge-distribution")
async def knowledge_distribution(
    top_n: int | None = None,
    u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
    s: AsyncSession = Depends(get_session),
):
    """企业知识数量分布：取最新流水中的分布数据（饼图）。"""
    from kb_common.clients import dingtalk_client as dt
    await dt.sync_runtime_config()
    await _hydrate_snapshot()
    kc = _snapshot.get("knowledge_count") or {}
    items = list(kc.get("distribution") or [])
    if top_n and top_n > 0:
        items = items[:top_n]
    return {
        "items": items,
        "error": None,
        "loading": bool(dt.is_configured() and _job["running"] and not items),
    }


@router.get("/hot-documents")
async def hot_documents(u=Depends(require_role("super_admin", "admin", "editor", "viewer")),
                        s: AsyncSession = Depends(get_session)):
    """热门知识 Top20：展示最新流水记录；扫描进行中时返回实时进度与部分排名。"""
    from kb_common.clients import dingtalk_client as dt
    await dt.sync_runtime_config()
    await _hydrate_snapshot()
    if dt.is_configured() and _is_stale() and not _job["running"]:
        _start_job("daily")

    hot_phase = _job["running"] and _job["phase"] == "hot"
    hd = _snapshot.get("hot_docs") or {}
    if hot_phase:
        items = _top_hot_docs()               # 扫描中的实时部分排名
        scanned, total = _hot_cache["scanned"], _hot_cache["total"]
    else:
        items = hd.get("items") or []
        scanned, total = hd.get("scanned", len(items)), hd.get("total", 0)
    return {
        "items": items,
        "scanned": scanned,
        "total": total,
        "loading": bool(hot_phase),
        "error": None,
        "updated_at": hd.get("created_at"),
    }


@router.post("/refresh-dingtalk")
async def refresh_dingtalk(u=Depends(require_role("super_admin", "admin")),
                           s: AsyncSession = Depends(get_session)):
    """手动刷新：立即重新全量统计（存储 → 数量 → 热门），结果写流水并更新展示。"""
    from kb_common.clients import dingtalk_client as dt
    await dt.sync_runtime_config()
    if not dt.is_configured():
        return {"ok": False, "error": "钉钉未配置"}
    started = _start_job("manual")
    return {"ok": True, "storage_error": None, "loading": True, "already_running": not started}
