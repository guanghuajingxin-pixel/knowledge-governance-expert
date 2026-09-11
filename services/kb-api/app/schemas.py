from pydantic import BaseModel, ConfigDict
import uuid
from datetime import datetime


class KbIn(BaseModel):
    name: str
    description: str | None = None
    kb_type: str = "DOCUMENT"
    chunk_strategy: str = "FIXED_SIZE"
    chunk_size: int = 512
    chunk_overlap: int = 150
    delimiter: str | None = None


class KbOut(KbIn):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    es_index_name: str
    document_count: int = 0
    owner_name: str = ""
    status: str = "正常"
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class DirIn(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


class DirOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    sort_order: int = 0
    document_count: int = 0
    children: list["DirOut"] = []

    class Config:
        from_attributes = True


class KcDocumentOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    kb_name: str = ""
    kb_type: str = ""
    directory_id: uuid.UUID | None = None
    directory_name: str | None = None
    original_filename: str
    file_type: str
    file_size: int = 0
    status: str
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class TrashItemOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    directory_name: str | None = None
    kb_name: str = ""
    operator_name: str = ""
    deleted_at: datetime | None = None
    remaining_days: int = 0


class TaskStatsOut(BaseModel):
    total: int = 0
    executing: int = 0
    completed: int = 0
    failed: int = 0


class SegmentOut(BaseModel):
    id: uuid.UUID
    chunk_index: int
    content: str
    content_hash: str | None
    token_count: int
    page_number: int | None


# ===== 知识源登记（企业知识库注册表）=====
class KnowledgeSourceBase(BaseModel):
    name: str
    source_type: str  # dingtalk_workspace | dify_dataset | business_system
    external_id: str
    description: str = ""
    config: dict | None = None
    enabled: bool = True


class KnowledgeSourceCreate(KnowledgeSourceBase):
    pass


class KnowledgeSourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    external_id: str | None = None
    description: str | None = None
    config: dict | None = None
    enabled: bool | None = None


class KnowledgeSourceOut(KnowledgeSourceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


# ===== 钉钉知识库 → Dify 定时增量同步 =====
from pydantic import Field


class SyncSourceBase(BaseModel):
    name: str
    workspace_id: str
    root_node_id: str
    start_dir: str = ""
    dify_dataset_name: str
    delete_policy: str = Field(default="keep", pattern="^(keep|sync)$")
    cron: str = "0 2 * * *"
    enabled: bool = True


class SyncSourceCreate(SyncSourceBase):
    pass


class SyncSourceTest(SyncSourceBase):
    """保存前连接测试使用的同步源草稿。"""
    pass


class SyncSourceUpdate(BaseModel):
    name: str | None = None
    workspace_id: str | None = None
    root_node_id: str | None = None
    start_dir: str | None = None
    dify_dataset_name: str | None = None
    delete_policy: str | None = Field(default=None, pattern="^(keep|sync)$")
    cron: str | None = None
    enabled: bool | None = None


class SyncPreviewItemSetting(BaseModel):
    node_id: str
    name: str = ""
    category: str = "DOCUMENT"
    enabled: bool


class SyncPreviewSettingsUpdate(BaseModel):
    items: list[SyncPreviewItemSetting]


class SyncSourceOut(SyncSourceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dify_dataset_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
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


class SyncFailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    source_id: int
    node_id: str | None
    name: str
    error: str
    created_at: datetime


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int | None
    level: str
    message: str
    created_at: datetime
