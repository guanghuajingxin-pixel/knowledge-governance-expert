"""同步数据库会话（同步版）。

平台主数据库 SessionLocal 是异步（asyncpg）的，而同步引擎沿用源项目同步实现
（httpx.Client + subprocess + 同步 ORM），运行于后台线程池中，不会阻塞事件循环。
这里基于 psycopg 建一个同步 engine/SessionLocal，连接同一套数据库。
"""
from __future__ import annotations

from pathlib import Path

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


def _default_data_dir() -> Path:
    base = Path(__file__).resolve().parents[3]  # services/kb-api
    return base / "data"


sync_engine = create_engine(_sync_database_url(), pool_pre_ping=True, echo=False, future=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, class_=Session)


def get_sync_session() -> Session:
    """同步引擎内部使用：返回一个需手动 close 的 Session。"""
    return SyncSessionLocal()
