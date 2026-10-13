"""顶栏运营指标：全部从业务表实时聚合，禁止硬编码。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from kb_common.database import get_session
from kb_common.models import (
    Document,
    QaFeedback,
    SyncDocumentMapping,
)
from app.deps import get_current_user

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

# 业务时区：产品面向国内企业，"今日"按 Asia/Shanghai 的自然日划分。
_USER_TZ = ZoneInfo("Asia/Shanghai")
_UTC = ZoneInfo("UTC")


def _day_start() -> datetime:
    """今日 0 点，换算为与库内时间戳可比的 naive UTC。

    documents/sync_document_mappings/qa_feedbacks 等表的
    created_at/updated_at 由 PG func.now() 写入，为容器 UTC 时钟的 naive 时间戳；
    若直接用进程本地时间的 0 点做 cutoff，会与列值错开 8 小时（凌晨时段漏算当日数据）。
    """
    day_start = datetime.now(_USER_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start.astimezone(_UTC).replace(tzinfo=None)


@router.get("/overview")
async def metrics_overview(
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    """顶栏三项指标口径：

    - today_new 今日新增：今日进入系统的知识文档数
      = 本地知识库上传(documents) + 同步采集新发现(sync_document_mappings)
    - total_adopted 累计采纳：问答反馈「有帮助」累计条数
    - total_feedback 累计反馈：问答反馈全部累计条数
    """
    day_start = _day_start()

    # 4 个计数合并成一条 SQL（标量子查询）：避免多次串行往返，
    # 顶栏每次整页加载都要等它，本机负载高时聚合慢会被放大。
    row = (await s.execute(select(
        select(func.count(Document.id)).where(
            Document.is_deleted == False,  # noqa: E712
            Document.created_at >= day_start,
        ).scalar_subquery().label("upload_new"),
        select(func.count(SyncDocumentMapping.id)).where(
            SyncDocumentMapping.created_at >= day_start,
        ).scalar_subquery().label("sync_new"),
        select(func.count(QaFeedback.id)).where(
            QaFeedback.feedback_type == "helpful",
        ).scalar_subquery().label("adopted"),
        select(func.count(QaFeedback.id)).scalar_subquery().label("feedback"),
    ))).one()

    return {
        "today_new": (row.upload_new or 0) + (row.sync_new or 0),
        "total_adopted": row.adopted or 0,
        "total_feedback": row.feedback or 0,
    }
