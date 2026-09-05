from pydantic import BaseModel
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
