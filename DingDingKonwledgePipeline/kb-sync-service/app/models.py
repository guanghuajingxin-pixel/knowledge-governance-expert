"""SQLAlchemy 数据模型"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class SyncSource(Base):
    __tablename__ = "sync_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    root_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    start_dir: Mapped[str] = mapped_column(String(500), default="")
    dify_dataset_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dify_dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delete_policy: Mapped[str] = mapped_column(String(10), default="keep")  # keep | sync
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    jobs: Mapped[list["SyncJob"]] = relationship(back_populates="source", cascade="all, delete-orphan")
    mappings: Mapped[list["DocumentMapping"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sync_sources.id"), nullable=True)
    cron: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source: Mapped["SyncSource"] = relationship(back_populates="jobs")
    runs: Mapped[list["SyncRun"]] = relationship(back_populates="job")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"), nullable=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sync_sources.id"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | schedule
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | partial | failed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")

    job: Mapped["SyncJob | None"] = relationship(back_populates="runs")
    failures: Mapped[list["SyncFailure"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    logs: Mapped[list["SyncLog"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class DocumentMapping(Base):
    __tablename__ = "document_mappings"
    __table_args__ = (UniqueConstraint("source_id", "node_id", name="uq_source_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sync_sources.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_node_id: Mapped[str] = mapped_column(String(128), default="")
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1000), default="")
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # DOCUMENT | ALIDOC
    meta_hash: Mapped[str] = mapped_column(String(128), default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="")
    local_path: Mapped[str] = mapped_column(String(1000), default="")
    dify_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dify_batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | synced | error
    error: Mapped[str] = mapped_column(Text, default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source: Mapped["SyncSource"] = relationship(back_populates="mappings")


class SyncFailure(Base):
    __tablename__ = "sync_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sync_sources.id"), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped["SyncRun"] = relationship(back_populates="failures")


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped["SyncRun | None"] = relationship(back_populates="logs")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
