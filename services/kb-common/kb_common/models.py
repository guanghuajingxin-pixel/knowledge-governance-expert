import uuid
from datetime import datetime, date
from sqlalchemy import String, Text, Integer, BigInteger, Boolean, DateTime, Date, JSON, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # super_admin|admin|editor|viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    kb_type: Mapped[str] = mapped_column(String(20))  # DOCUMENT | FAQ
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    chunk_strategy: Mapped[str] = mapped_column(String(30), default="FIXED_SIZE")
    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=150)
    delimiter: Mapped[str | None] = mapped_column(String(50))  # Delimiter 策略分隔符
    embedding_model: Mapped[str] = mapped_column(String(100), default="bge-m3")
    es_index_name: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="FULLY_PUBLISHED")  # PUBLISHING|FULLY_PUBLISHED|PARTIALLY_FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KbFavorite(Base):
    __tablename__ = "kb_favorites"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Directory(Base):
    __tablename__ = "directories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("directories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    directory_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("directories.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000))   # MinIO raw key
    parsed_path: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # PENDING->PARSING->CHUNKING->EMBEDDING->INDEXING->COMPLETED|FAILED
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    faq_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("faq_entries.id", ondelete="CASCADE"))
    es_chunk_id: Mapped[str | None] = mapped_column(String(100))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class FaqDirectory(Base):
    __tablename__ = "faq_directories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("faq_directories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

class FaqEntry(Base):
    __tablename__ = "faq_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    directory_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("faq_directories.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(ARRAY(String), default=list)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT|INDEXED|FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Setting(Base):
    """运行时可配置项（LLM/MinerU key 等），覆盖 .env 默认值。"""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)


class DifyProfile(Base):
    """多条 Dify 配置，只能生效一条（enabled=true）。"""
    __tablename__ = "dify_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    dataset_ids: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LLMProfile(Base):
    """LLM 供应商配置：一个供应商一条；models 为 JSON 数组。

    models 结构：[{"name": "deepseek-chat", "enabled": true, "is_default": false}, ...]
    - enabled=true 的模型出现在智能问答模型选项中
    - 全局仅一个模型 is_default=true，作为新会话默认模型
    """
    __tablename__ = "llm_profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(32), default="custom")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    models: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatSession(Base):
    """智能问答会话：每个会话独立隔离，拥有各自的记忆文档。"""
    __tablename__ = "chat_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    # 会话记忆文档：持续浓缩的对话摘要，用于多轮改写与长期记忆
    memory: Mapped[str] = mapped_column(Text, default="")
    last_query: Mapped[str] = mapped_column(Text, default="")
    last_answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    """会话内的单条消息（user / assistant）。"""
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))           # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(ARRAY(String), default=list)  # 引用文档标题
    meta: Mapped[str | None] = mapped_column(Text)          # 元信息（模型/召回数等）
    detail: Mapped[dict | None] = mapped_column(JSON)       # 回答链路/召回片段 {steps, retrieval, model, duration_ms}
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UsageLog(Base):
    """知识调用日志：记录每次检索/问答，用于运营看板统计召回数、调用量、热门知识。"""
    __tablename__ = "usage_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scene: Mapped[str] = mapped_column(String(20))   # search | chat
    query: Mapped[str | None] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)           # 召回条数
    hit_document_ids: Mapped[list] = mapped_column(ARRAY(String), default=list)  # 命中的文档 ID
    hit_document_titles: Mapped[list] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OperateMetricRecord(Base):
    """运营看板指标流水：每日 0 点定时（或手动刷新）写入，展示取各指标最新一条。

    metric_key: storage（知识存储总量）| knowledge_count（知识数量+分布）| hot_docs（热门知识Top20）
    value: 指标内容 JSON（含 metric_date/created_at 口径信息）
    """
    __tablename__ = "operate_metric_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_key: Mapped[str] = mapped_column(String(32), index=True)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    value: Mapped[dict] = mapped_column(JSON)
    trigger: Mapped[str] = mapped_column(String(16), default="daily")  # daily | manual
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class QaFeedback(Base):
    """问答反馈：点赞(helpful)/纠错(correct)/没找到(notfound)。纠错类进入「知识纠错」工单流。"""
    __tablename__ = "qa_feedbacks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)  # 助手消息 ID
    feedback_type: Mapped[str] = mapped_column(String(20), index=True)  # helpful | correct | notfound
    knowledge_title: Mapped[str | None] = mapped_column(String(500))    # 知识标题（纠错时可指定）
    knowledge_url: Mapped[str | None] = mapped_column(String(1000))     # 知识链接（钉钉文档/Dify/预览URL）
    error_type: Mapped[str | None] = mapped_column(String(32))          # 内容错误/知识重复/知识过期/知识难理解/知识不完整/知识模板错误/其它
    content: Mapped[str | None] = mapped_column(Text)                   # 纠错/反馈说明
    question: Mapped[str | None] = mapped_column(Text)                  # 当时的问题（冗余，便于工单展示）
    # 工单处理
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | processing | resolved | closed
    handler_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handler_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
