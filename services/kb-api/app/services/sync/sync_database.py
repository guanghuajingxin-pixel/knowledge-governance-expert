"""同步数据库会话（同步版）。

平台主数据库 SessionLocal 是异步（asyncpg）的，而同步引擎沿用源项目同步实现
（httpx.Client + subprocess + 同步 ORM），运行于后台线程池中，不会阻塞事件循环。
这里基于 psycopg 建一个同步 engine/SessionLocal，连接同一套数据库。
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from kb_common.config import get_settings


def _sync_database_url() -> str:
    """将 postgresql+asyncpg://... 转为 postgresql+psycopg://..."""
    url = get_settings().database_url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url
    # 其它 dialect 不做转换，交给 SQLAlchemy 报错
    return url


_s = get_settings()
# 新建连接超时：数据库/容器侧抖动时 psycopg 默认会长时间挂住，
# 而同步路由跑在线程池里，一个挂住的连接会连带拖慢整批 /api/v1/sync/* 请求。
_connect_args: dict = {}
if _sync_database_url().startswith("postgresql+psycopg://"):
    _connect_args["connect_timeout"] = _s.db_pool_timeout

# 与异步引擎共用同一套池参数：/api/v1/sync/* 全是同步 def 路由（跑在线程池里），
# 前端同步页每 3 秒并发 2+N 个请求，后台同步任务还会长时间持有会话，
# 默认 5+10/30s 同样会被抽干，表现为整站点击卡顿。
sync_engine = create_engine(_sync_database_url(), pool_pre_ping=True, echo=False, future=True,
                            pool_size=_s.db_pool_size, max_overflow=_s.db_max_overflow,
                            pool_timeout=_s.db_pool_timeout, pool_recycle=_s.db_pool_recycle,
                            connect_args=_connect_args)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, class_=Session)


def get_sync_session() -> Session:
    """同步引擎内部使用：返回一个需手动 close 的 Session。"""
    return SyncSessionLocal()
