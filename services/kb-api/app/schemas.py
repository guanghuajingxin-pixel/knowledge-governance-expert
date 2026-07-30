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
    status: str = "FULLY_PUBLISHED"
    document_count: int = 0
    owner_name: str = ""
    is_favorite: bool = False
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class DirIn(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


class SegmentOut(BaseModel):
    id: uuid.UUID
    chunk_index: int
    content: str
    content_hash: str | None
    token_count: int
    page_number: int | None
