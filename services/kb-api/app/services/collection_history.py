"""Record uploads without retaining local files or expiring download URLs."""
from datetime import datetime
from functools import wraps
from kb_common.models import CollectionTransfer


def track_transfer(kind):
    def decorate(function):
        @wraps(function)
        async def tracked(*args, **kwargs):
            session = kwargs["s"]
            name = kwargs["file"].filename if kind == "upload" else kwargs["body"].name
            record = CollectionTransfer(kind=kind, name=(name or "untitled")[:500],
                dataset_id=kwargs["dataset_id"], status="running", message="")
            session.add(record)
            await session.commit()
            try:
                result = await function(*args, **kwargs)
            except Exception as exc:
                record.status = "failed"
                record.message = str(getattr(exc, "detail", str(exc)))[:2000]
                record.finished_at = datetime.utcnow()
                await session.commit()
                raise
            record.status = "success"
            record.document_id = result.get("document_id")
            record.message = "已写入 Dify；解析及索引结果请到目标知识库检查"
            record.finished_at = datetime.utcnow()
            await session.commit()
            return result
        return tracked
    return decorate
