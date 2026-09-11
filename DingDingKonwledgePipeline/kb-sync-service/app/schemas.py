"""请求/响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceBase(BaseModel):
    name: str
    workspace_id: str
    root_node_id: str
    start_dir: str = ""
    dify_dataset_name: str
    delete_policy: str = Field(default="keep", pattern="^(keep|sync)$")
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = None
    workspace_id: str | None = None
    root_node_id: str | None = None
    start_dir: str | None = None
    dify_dataset_name: str | None = None
    delete_policy: str | None = Field(default=None, pattern="^(keep|sync)$")
    enabled: bool | None = None


class SourceOut(SourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dify_dataset_id: str | None = None
    created_at: datetime
    updated_at: datetime


class JobBase(BaseModel):
    name: str
    source_id: int | None = None
    cron: str
    description: str = ""
    enabled: bool = True


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    name: str | None = None
    source_id: int | None = None
    cron: str | None = None
    description: str | None = None
    enabled: bool | None = None


class JobOut(JobBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None
    source_id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    total: int
    created_count: int
    updated_count: int
    deleted_count: int
    failed_count: int
    message: str


class FailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    source_id: int
    node_id: str | None
    name: str
    error: str
    created_at: datetime


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    level: str
    message: str
    created_at: datetime


class SettingsOut(BaseModel):
    dingtalk_webhook: str
    alert_failure_threshold: int
    default_delete_policy: str
    export_format: str
    max_depth: int
    dify_wait_indexing: bool
    dingtalk_operator_id: str


class SettingsUpdate(BaseModel):
    dingtalk_webhook: str | None = None
    alert_failure_threshold: int | None = None
    default_delete_policy: str | None = None
    export_format: str | None = None
    max_depth: int | None = None
    dify_wait_indexing: bool | None = None
    dingtalk_operator_id: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
