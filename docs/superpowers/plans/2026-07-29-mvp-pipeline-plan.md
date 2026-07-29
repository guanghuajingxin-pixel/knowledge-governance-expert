# 知识库 MVP 流水线实现计划（1 周端到端跑通）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 1 周内把「知识采集 → 知识加工 → 知识应用」端到端跑通：上传文档 → MinerU 解析 → 切片 → BGE-M3 向量化 → ES 索引 → 混合检索 + 重排 → 溯源 → LLM 问答生成；并独立提供 FAQ 服务。

**Architecture:** 3 进程架构（用户已确认）：
- `kb-api`（FastAPI）：auth + knowledge + rag 三模块合一，进程内加载 BGE-M3 / BGE-reranker（FlagEmbedding），对内暴露 `/internal/embed` `/internal/rerank`。
- `faq-service`（FastAPI，独立进程）：FAQ KB/目录/条目 CRUD + 批量导入 + FAQ 检索，向量化与检索通过调用 kb-api 内部接口完成（模型只加载一次）。
- `kb-worker`（Celery）：文档异步采集流水线（MinerU 解析 → 切片 → 调 kb-api 批量向量化 → ES 索引 → 回写状态）。
- 基础设施复用已有开发环境（PG16 / ES / MinIO / Redis / kkFileView），MinerU 走公有云 API，LLM 接 GLM/DeepSeek。

**Tech Stack:** Python 3.11（uv 管理）· FastAPI · SQLAlchemy 2.0(async) + asyncpg · Alembic · Celery + Redis · Elasticsearch 8.15 · MinIO · FlagEmbedding(bge-m3 + bge-reranker-v2-m3) · MinerU Cloud API · GLM/DeepSeek(OpenAI 兼容) · Vue3 + TS + Element Plus（复用前端计划）。

## Global Constraints

- **Python 版本**：锁定 3.11（系统自带 3.14，torch/FlagEmbedding 无 3.14 wheel）。用 `uv` 管理 venv 与依赖；`uv python install 3.11`。
- **运行模式**：开发期基础设施跑在 Docker（已有 dev 环境），三个应用进程 **本地原生运行**（`uv run uvicorn` / `uv run celery`），以便 BGE 模型使用 Mac 原生内存（colima 4GB 不够装模型）。Docker 全量打包模式作为 Task 12 交付。
- **复用基础设施连接信息**（来自 `/Users/hjx/Documents/03_Resource/开发环境`）：
  - PG：`postgresql+asyncpg://dev:dev123456@127.0.0.1:5432/dev_db`
  - Redis：`redis://:dev123456@127.0.0.1:6379/0`
  - ES：`http://127.0.0.1:9200`（安全关闭）
  - MinIO：`127.0.0.1:9000`（AK/SK = minioadmin/minioadmin）
  - kkFileView：`http://127.0.0.1:8012`
- **向量/重排模型**：本地部署，FlagEmbedding 进程内推理（kb-api 加载），bge-m3 输出 1024 维稠密向量。
- **MinerU**：公有云 API（API Key 经前端/`.env` 配置）。
- **LLM**：OpenAI 兼容协议接入 GLM / DeepSeek，`base_url` + `api_key` + `model` 可配置。
- **ES 索引**：每个知识库独立索引 `kb_{kb_id}`，mapping 含溯源字段（见设计文档）。
- **认证**：JWT(HS256) 共享密钥；角色 `super_admin|admin|editor|viewer`；kb-api 与 faq-service 共用同一 JWT 密钥，faq-service 自验 JWT。
- **代码风格**：FastAPI 路由用 APIRouter；Pydantic v2；异步 DB；函数命名 snake_case；中文注释关键逻辑。
- **Dify 参考**：`dify/api/core/rag/` 下的 extractor/splitter/embedding/retrieval/rerank 作为实现参考，不直接 import。
- **提交粒度**：每个 Task 结束一次 commit，信息 `feat(<scope>): <desc>`。

## 1 周排期

| 天 | 任务 | 产出 |
|----|------|------|
| D1 | Task 1-3 | 仓库骨架、数据模型迁移、基础设施客户端（ES/MinIO/Celery/MinerU/LLM/FlagEmbedding） |
| D2 | Task 4-5 | auth(JWT+RBAC+用户+APIKey) + knowledge(KB CRUD + 目录树) |
| D3 | Task 6-7 | 文档上传/切片预览 + rag(chunker+embedder+indexer+searcher+reranker+tracer+检索API) |
| D4 | Task 8-9 | LLM 问答 + kb-worker 异步流水线 |
| D5 | Task 10 | faq-service 独立服务 |
| D6 | Task 11 | 前端接真实后端 + 模型配置页 |
| D7 | Task 12 | docker-compose 一键 + 端到端冒烟 + README |

## 目录结构（MVP 终态）

```
knowledge-base/
├── docker-compose.app.yml          # 应用三进程（Docker 模式）
├── .env                            # 应用配置（含 MinerU/LLM key 占位）
├── services/
│   ├── kb-common/                  # 共享包（uv 本地依赖）
│   │   ├── pyproject.toml
│   │   └── kb_common/
│   │       ├── __init__.py
│   │       ├── config.py           # Settings（pydantic-settings）
│   │       ├── database.py         # async engine + session
│   │       ├── models.py           # 全部 ORM 模型
│   │       ├── schemas.py          # 共享 Pydantic
│   │       ├── security.py         # JWT/hash
│   │       ├── clients/
│   │       │   ├── es_client.py    # ES 客户端 + 索引模板
│   │       │   ├── minio_client.py # MinIO 客户端 + bucket 初始化
│   │       │   ├── mineru_client.py# MinerU 公有云客户端
│   │       │   ├── llm_client.py   # OpenAI 兼容 LLM 客户端
│   │       │   └── tei_client.py   # （预留，当前用本地 FlagEmbedding）
│   │       └── rag/
│   │           ├── embedder.py     # FlagEmbedding bge-m3（单例）
│   │           ├── reranker.py     # FlagEmbedding bge-reranker-v2-m3（单例）
│   │           ├── chunker.py      # FixedSize + Delimiter 策略
│   │           ├── indexer.py      # ES 索引创建 + bulk 写入
│   │           ├── searcher.py     # kNN + BM25 + RRF
│   │           └── tracer.py       # 溯源字段组装
│   ├── kb-api/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── main.py             # FastAPI 入口
│   │       ├── deps.py             # 依赖注入（current_user 等）
│   │       ├── routes/
│   │       │   ├── auth.py         # login/users/api-keys
│   │       │   ├── knowledge_base.py
│   │       │   ├── directory.py
│   │       │   ├── document.py
│   │       │   ├── search.py       # /api/v1/search + /trace + /chat
│   │       │   ├── settings_route.py # 模型配置
│   │       │   └── internal.py     # /internal/embed /internal/rerank /internal/index
│   │       ├── services/
│   │       │   ├── ingestion.py    # 上传编排
│   │       │   ├── pipeline.py     # 同步索引（可选）
│   │       │   └── chat.py         # RAG 问答
│   │       └── worker.py           # Celery app + ingestion 任务
│   ├── faq-service/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── main.py
│   │       ├── deps.py
│   │       ├── routes/{kb,directory,entry,search}.py
│   │       └── services/{faq_import,faq_index,faq_search}.py
│   └── kb-worker/                  # （可选独立镜像；MVP 复用 kb-api 镜像 + celery 命令）
├── web/                            # Vue3 前端（复用前端计划，接真实 API）
├── alembic/                        # 迁移（kb-common 模型）
├── alembic.ini
└── dify/                           # 参考源码
```

---

## Task 1: 仓库骨架 + kb-common 包 + 依赖 + 配置

**Files:**
- Create: `services/kb-common/pyproject.toml`
- Create: `services/kb-common/kb_common/__init__.py`
- Create: `services/kb-common/kb_common/config.py`
- Create: `.env.example`、`.env`
- Create: `docker-compose.app.yml`
- Create: `.gitignore`（补 `services/**/.venv` `__pycache__` `.env` `web/node_modules` `web/dist`）
- Create: `.python-version`（`3.11`）

**Interfaces:**
- Produces: `kb_common.config.Settings`（单例 `get_settings()`），供所有服务 import。

- [ ] **Step 1: 安装 uv 并准备 Python 3.11**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 已装可跳过
uv python install 3.11
echo "3.11" > .python-version
```

- [ ] **Step 2: 初始化 kb-common 包**

`services/kb-common/pyproject.toml`:
```toml
[project]
name = "kb-common"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = [
  "fastapi>=0.110",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.29",
  "alembic>=1.13",
  "elasticsearch[async]>=8.13",
  "minio>=7.2",
  "redis>=5.0",
  "celery>=5.4",
  "FlagEmbedding>=1.2.7",
  "openai>=1.30",          # GLM/DeepSeek 兼容客户端
  "python-multipart>=0.0.9",
  "httpx>=0.27",
  "python-jose[cryptography]>=3.3",
  "passlib[bcrypt]>=1.7",
]
```
```bash
mkdir -p services/kb-common/kb_common/clients services/kb-common/kb_common/rag
touch services/kb-common/kb_common/__init__.py
```

- [ ] **Step 3: 写 config.py**

`services/kb-common/kb_common/config.py`:
```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 基础设施
    database_url: str = "postgresql+asyncpg://dev:dev123456@127.0.0.1:5432/dev_db"
    redis_url: str = "redis://:dev123456@127.0.0.1:6379/0"
    es_host: str = "http://127.0.0.1:9200"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    kkfv_url: str = "http://127.0.0.1:8012"

    # 认证
    jwt_secret: str = "change-me-in-prod"
    jwt_algo: str = "HS256"
    jwt_ttl_minutes: int = 1440

    # 模型
    bge_embed_model: str = "BAAI/bge-m3"
    bge_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    embed_dim: int = 1024
    mineru_api_url: str = "https://mineru.net/api/v4"
    mineru_api_key: str = ""          # 运行时可被 settings 表覆盖

    # LLM（默认 GLM；DeepSeek 同协议）
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""
    llm_model: str = "glm-4-flash"

    # 服务间
    kb_api_internal_url: str = "http://127.0.0.1:8000"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: .env 与 docker-compose.app.yml**

`.env.example`（复制为 `.env` 填真实 key）:
```env
DATABASE_URL=postgresql+asyncpg://dev:dev123456@127.0.0.1:5432/dev_db
REDIS_URL=redis://:dev123456@127.0.0.1:6379/0
ES_HOST=http://127.0.0.1:9200
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
KKFV_URL=http://127.0.0.1:8012
JWT_SECRET=kb-mvp-dev-secret
MINERU_API_KEY=
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=
LLM_MODEL=glm-4-flash
```

`docker-compose.app.yml`（Docker 全量模式，加入 dev 网络复用基础设施）:
```yaml
name: kb-app
services:
  kb-api:
    build: ./services/kb-api
    ports: ["8000:8000"]
    env_file: .env
    networks: [dev-network]
  faq-service:
    build: ./services/faq-service
    ports: ["8004:8004"]
    env_file: .env
    networks: [dev-network]
  kb-worker:
    build: ./services/kb-api
    command: celery -A app.worker worker -Q ingestion --concurrency=2 -l info
    env_file: .env
    networks: [dev-network]
networks:
  dev-network:
    external: true
```
> 注：Docker 模式下 `MINIO_ENDPOINT=dev-minio:9000`、`ES_HOST=http://dev-elasticsearch:9200`、`DATABASE_URL=...@dev-postgres:5432/dev_db`，需在 `.env.docker` 覆盖。

- [ ] **Step 5: 验证依赖可装**

```bash
cd services/kb-common && uv sync
```
Expected: 虚拟环境创建成功，依赖安装完成（FlagEmbedding 会拉 torch，首次较慢）。

- [ ] **Step 6: Commit**

```bash
git add services/kb-common .env.example docker-compose.app.yml .python-version .gitignore
git commit -m "feat(scaffold): kb-common 包与项目骨架"
```

---

## Task 2: 数据模型 + Alembic 迁移 + seed

**Files:**
- Create: `services/kb-common/kb_common/database.py`
- Create: `services/kb-common/kb_common/models.py`
- Create: `alembic.ini`、`alembic/env.py`、`alembic/script.py.mako`
- Create: `alembic/versions/0001_init.py`
- Create: `scripts/seed_admin.py`

**Interfaces:**
- Produces: `kb_common.database.get_session`（async session 工厂）、`kb_common.models.*`（全部表）。

- [ ] **Step 1: database.py**

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from kb_common.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_session() -> AsyncSession:
    async with SessionLocal() as s:
        yield s
```

- [ ] **Step 2: models.py（UUID 主键 + 7 张业务表 + settings 表）**

```python
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, BigInteger, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
```

- [ ] **Step 3: 初始化 Alembic 并生成迁移**

```bash
uv run alembic init alembic
```
编辑 `alembic/env.py`，`target_metadata = Base.metadata`，`import kb_common.models`，使用 `settings.database_url`。
```bash
uv run alembic revision --autogenerate -m "init schema"
uv run alembic upgrade head
```
Expected: PG 中出现 8 张表。

- [ ] **Step 4: seed admin 用户**

`scripts/seed_admin.py`:
```python
import asyncio
from kb_common.database import SessionLocal
from kb_common.models import User
from kb_common.security import hash_password

async def main():
    async with SessionLocal() as s:
        admin = User(username="admin", password_hash=hash_password("admin123"),
                     role="super_admin", email="admin@kb.local")
        s.add(admin); await s.commit()
    print("admin / admin123 created")

asyncio.run(main())
```
`kb_common/security.py`:
```python
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, timezone
from kb_common.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"])

def hash_password(p: str) -> str: return _pwd.hash(p)
def verify_password(p: str, h: str) -> bool: return _pwd.verify(p, h)

def create_jwt(user_id: str, role: str) -> str:
    s = get_settings()
    payload = {"sub": user_id, "role": role,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algo)

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algo])
```
```bash
uv run python scripts/seed_admin.py
```
Expected: `admin / admin123 created`。

- [ ] **Step 5: Commit**

```bash
git add services/kb-common alembic alembic.ini scripts
git commit -m "feat(db): 数据模型与 Alembic 迁移 + admin seed"
```

---

## Task 3: 基础设施客户端（ES / MinIO / Celery / MinerU / LLM / FlagEmbedding）

**Files:**
- Create: `services/kb-common/kb_common/clients/es_client.py`
- Create: `services/kb-common/kb_common/clients/minio_client.py`
- Create: `services/kb-common/kb_common/clients/mineru_client.py`
- Create: `services/kb-common/kb_common/clients/llm_client.py`
- Create: `services/kb-common/kb_common/rag/embedder.py`
- Create: `services/kb-common/kb_common/rag/reranker.py`

**Interfaces:**
- Produces:
  - `es_client.ensure_index(kb_id) -> str`（返回索引名）
  - `es_client.bulk_index(index, docs)`
  - `embedder.embed(texts: list[str]) -> list[list[float]]`（1024 维）
  - `reranker.rerank(query, docs: list[dict], top_n) -> list[dict]`
  - `mineru_client.parse(file_bytes, filename) -> dict`（返回 markdown/正文）
  - `llm_client.chat(messages) -> str`

- [ ] **Step 1: ES 客户端 + 索引模板（含溯源字段）**

```python
from elasticsearch import AsyncElasticsearch
from kb_common.config import get_settings

_s = get_settings()
es = AsyncElasticsearch(_s.es_host)

MAPPING = {
  "mappings": {"properties": {
    "text": {"type": "text", "analyzer": "standard"},
    "vector": {"type": "dense_vector", "dims": 1024, "similarity": "cosine", "index": True},
    "kb_id": {"type": "keyword"}, "kb_type": {"type": "keyword"},
    "document_id": {"type": "keyword"}, "faq_entry_id": {"type": "keyword"},
    "chunk_index": {"type": "integer"}, "total_chunks": {"type": "integer"},
    "source_type": {"type": "keyword"}, "source_path": {"type": "keyword"},
    "document_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
    "file_type": {"type": "keyword"}, "page_number": {"type": "integer"},
    "directory_id": {"type": "keyword"}, "directory_path": {"type": "text"},
    "faq_answer": {"type": "text"},
    "preview_url": {"type": "keyword"}, "preview_type": {"type": "keyword"},
    "content_hash": {"type": "keyword"}, "token_count": {"type": "integer"},
    "created_at": {"type": "date"}
  }}
}

async def ensure_index(kb_id: str) -> str:
    name = f"kb_{kb_id.replace('-', '')}"
    if not await es.indices.exists(index=name):
        await es.indices.create(index=name, **MAPPING)
    return name

async def bulk_index(index: str, docs: list[dict]):
    actions = []
    for d in docs:
        actions.append({"index": {"_index": index}})
        actions.append(d)
    await es.bulk(operations=actions, refresh=True)

async def delete_by_doc(index: str, document_id: str):
    await es.delete_by_query(index=index, body={"query": {"term": {"document_id": document_id}}})
```

- [ ] **Step 2: MinIO 客户端**

```python
from minio import Minio
from kb_common.config import get_settings
_s = get_settings()
minio = Minio(_s.minio_endpoint, access_key=_s.minio_access_key,
              secret_key=_s.minio_secret_key, secure=False)
RAW = "raw-docs"; PARSED = "parsed-docs"
for b in (RAW, PARSED):
    if not minio.bucket_exists(b): minio.make_bucket(b)
```

- [ ] **Step 3: MinerU 公有云客户端（OpenAPI 兼容封装）**

```python
import httpx
from kb_common.config import get_settings

async def parse(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """调用 MinerU 公有云 API 解析文档，返回 {'markdown': str, 'pages': int}。
    实际 endpoint 以 mineru.net 文档为准；此处为标准封装，含 API Key 头。"""
    s = get_settings()
    key = api_key or s.mineru_api_key
    async with httpx.AsyncClient(timeout=300) as c:
        # 1. 申请上传 URL / 提交任务（按 MinerU 云文档实现）
        # 2. 轮询任务结果
        # 3. 取回 markdown
        # —— MVP 先以本地直解兜底（见下方 fallback）——
        return {"markdown": _local_fallback(file_bytes, filename), "pages": 1}

def _local_fallback(file_bytes: bytes, filename: str) -> str:
    """MinerU key 未配置时的本地兜底：纯文本/markdown 直读；其他格式提示配置 key。"""
    import io
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "md"):
        return file_bytes.decode("utf-8", errors="ignore")
    if ext in ("csv",):
        return file_bytes.decode("utf-8", errors="ignore")
    # doc/docx/pdf/xlsx：需 MinerU 云；未配置则抛错由 worker 标 FAILED
    if not get_settings().mineru_api_key:
        raise RuntimeError("MINERU_API_KEY 未配置，无法解析二进制文档")
    raise RuntimeError("MinerU 云解析未实现，请在 Task9 接入")
```
> 说明：MinerU 云 API 的确切请求/轮询流程在 Task 9 接入时按官方文档补全；MVP 先保证 txt/md/csv 走本地兜底跑通流水线。

- [ ] **Step 4: LLM 客户端（OpenAI 兼容，GLM/DeepSeek 通用）**

```python
from openai import AsyncOpenAI
from kb_common.config import get_settings

def _client(base_url: str | None = None, api_key: str | None = None) -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(base_url=base_url or s.llm_base_url,
                       api_key=api_key or s.llm_api_key or "empty")

async def chat(messages: list[dict], model: str | None = None,
               base_url: str | None = None, api_key: str | None = None) -> str:
    s = get_settings()
    resp = await _client(base_url, api_key).chat.completions.create(
        model=model or s.llm_model, messages=messages, temperature=0.2)
    return resp.choices[0].message.content or ""
```

- [ ] **Step 5: FlagEmbedding embedder + reranker（单例，kb-api 加载）**

`rag/embedder.py`:
```python
from FlagEmbedding import FlagModel
from kb_common.config import get_settings
_instance = None

def get_embedder():
    global _instance
    if _instance is None:
        s = get_settings()
        _instance = FlagModel(s.bge_embed_model, use_fp16=False,
                              devices=["cpu"])  # Mac 无 NVIDIA GPU，CPU 推理
    return _instance

def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, normalize_embeddings=True).tolist()
```
`rag/reranker.py`:
```python
from FlagEmbedding import FlagReranker
from kb_common.config import get_settings
_instance = None

def get_reranker():
    global _instance
    if _instance is None:
        _instance = FlagReranker(get_settings().bge_rerank_model, use_fp16=False)
    return _instance

def rerank(query: str, docs: list[dict], top_n: int = 10) -> list[dict]:
    if not docs: return []
    pairs = [[query, d["text"]] for d in docs]
    scores = get_reranker().compute_score(pairs, normalize=True)
    if isinstance(scores, float): scores = [scores]
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)[:top_n]
    for d, sc in ranked: d["rerank_score"] = float(sc)
    return [d for d, _ in ranked]
```

- [ ] **Step 6: 冒烟验证**

```bash
uv run python -c "
import asyncio
from kb_common.clients import es_client
async def t():
    n = await es_client.ensure_index('00000000-0000-0000-0000-000000000001')
    print('index:', n); await es_client.es.close()
asyncio.run(t())
"
uv run python -c "from kb_common.rag import embedder; print(len(embedder.embed(['你好'])[0]))"
```
Expected: `index: kb_00000000...`；`1024`（首次加载模型较慢）。

- [ ] **Step 7: Commit**

```bash
git add services/kb-common
git commit -m "feat(infra): ES/MinIO/MinerU/LLM/FlagEmbedding 客户端"
```

---

## Task 4: kb-api auth 模块 + 内部 embed/rerank 暴露

**Files:**
- Create: `services/kb-api/pyproject.toml`
- Create: `services/kb-api/app/main.py`
- Create: `services/kb-api/app/deps.py`
- Create: `services/kb-api/app/routes/auth.py`
- Create: `services/kb-api/app/routes/internal.py`
- Create: `services/kb-api/app/routes/users.py`
- Create: `services/kb-api/Dockerfile`

**Interfaces:**
- Consumes: `kb_common.security`, `kb_common.models`, `kb_common.rag.embedder/reranker`
- Produces: `POST /api/v1/auth/login` -> `{access_token, token_type, user}`；`/internal/embed`、`/internal/rerank`（供 faq-service / worker 调用）；`Depends(get_current_user)`、`Depends(require_role(...))`。

- [ ] **Step 1: kb-api 依赖**

`services/kb-api/pyproject.toml`:
```toml
[project]
name = "kb-api"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = ["kb-common", "uvicorn[standard]>=0.29"]
[tool.uv.sources]
kb-common = { path = "../kb-common", editable = true }
```
```bash
cd services/kb-api && uv sync
```

- [ ] **Step 2: deps.py（认证依赖）**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.security import decode_jwt
from kb_common.models import User

bearer = HTTPBearer()

async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                           s: AsyncSession = Depends(get_session)) -> User:
    try:
        payload = decode_jwt(cred.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效凭证")
    user = await s.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    return user

def require_role(*roles):
    async def checker(u: User = Depends(get_current_user)) -> User:
        if u.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return u
    return checker
```

- [ ] **Step 3: auth.py（登录）**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import User
from kb_common.security import verify_password, create_jwt
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class LoginIn(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(body: LoginIn, s: AsyncSession = Depends(get_session)):
    u = (await s.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return {"access_token": create_jwt(str(u.id), u.role),
            "token_type": "bearer",
            "user": {"id": str(u.id), "username": u.username, "role": u.role}}
```

- [ ] **Step 4: internal.py（对外不暴露，仅本机/服务间；MVP 用简单 token 或内网信任）**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from kb_common.rag import embedder, reranker

router = APIRouter(prefix="/internal", tags=["internal"])

class EmbedIn(BaseModel):
    texts: list[str]
class EmbedOut(BaseModel):
    vectors: list[list[float]]

@router.post("/embed", response_model=EmbedOut)
def embed(body: EmbedIn):
    return EmbedOut(vectors=embedder.embed(body.texts))

class RerankIn(BaseModel):
    query: str
    docs: list[dict]
    top_n: int = 10

@router.post("/rerank")
def rerank_(body: RerankIn):
    return {"results": reranker.rerank(body.query, body.docs, body.top_n)}
```

- [ ] **Step 5: users.py + api-keys（最小）**

```python
from fastapi import APIRouter, Depends
from kb_common.models import User, ApiKey
from kb_common.security import hash_password
from kb_common.config import get_settings
import secrets, hashlib
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/api/v1", tags=["users"])

@router.get("/users/me")
async def me(u: User = Depends(get_current_user)):
    return {"id": str(u.id), "username": u.username, "role": u.role}

class ApiKeyIn(BaseModel):
    name: str

@router.post("/auth/api-keys")
async def create_key(body: ApiKeyIn, u: User = Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    raw = "kb_" + secrets.token_hex(24)
    k = ApiKey(user_id=u.id, name=body.name, key_hash=hashlib.sha256(raw.encode()).hexdigest(),
               key_prefix=raw[:10])
    s.add(k); await s.commit()
    return {"id": str(k.id), "key": raw, "name": body.name}  # raw 仅此一次返回

@router.get("/auth/api-keys")
async def list_keys(u: User = Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    rows = (await s.execute(select(ApiKey).where(ApiKey.user_id == u.id))).scalars().all()
    return [{"id": str(r.id), "name": r.name, "prefix": r.key_prefix, "is_active": r.is_active} for r in rows]
```

- [ ] **Step 6: main.py 装配**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, users, internal

app = FastAPI(title="KB API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(internal.router)

@app.get("/health")
def health(): return {"status": "ok"}
```

- [ ] **Step 7: Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY . .
RUN uv sync
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 8: 启动并验证**

```bash
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
# 另一终端
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -m json.tool
```
Expected: 返回 `access_token`。

- [ ] **Step 9: Commit**

```bash
git add services/kb-api
git commit -m "feat(kb-api): auth 登录/JWT/RBAC + 内部 embed/rerank 接口"
```

---

## Task 5: kb-api knowledge 模块（KB CRUD + 目录树 + 文档上传/切片/预览）

**Files:**
- Create: `services/kb-api/app/routes/knowledge_base.py`
- Create: `services/kb-api/app/routes/directory.py`
- Create: `services/kb-api/app/routes/document.py`
- Create: `services/kb-api/app/services/ingestion.py`
- Create: `services/kb-api/app/schemas.py`

**Interfaces:**
- Consumes: `kb_common.clients.es_client.ensure_index`、`kb_common.clients.minio_client`
- Produces: KB/目录/文档全套对外 API；上传后入队 `ingestion`（Task 9 的 worker 消费）。

- [ ] **Step 1: schemas.py**

```python
from pydantic import BaseModel
import uuid

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
    es_index_name: str
    class Config: from_attributes = True

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
```

- [ ] **Step 2: knowledge_base.py（CRUD + 建索引）**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase
from kb_common.clients import es_client
from app.schemas import KbIn, KbOut
from app.deps import get_current_user
import uuid as _uuid

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["kb"])

@router.post("", response_model=KbOut)
async def create_kb(body: KbIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = KnowledgeBase(**body.model_dump(), owner_id=u.id,
                       es_index_name=f"kb_{_uuid.uuid4().hex}")
    s.add(kb); await s.commit(); await s.refresh(kb)
    await es_client.ensure_index(str(kb.id))
    return kb

@router.get("", response_model=list[KbOut])
async def list_kb(u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))).scalars().all()

@router.get("/{kb_id}", response_model=KbOut)
async def get_kb(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb: raise HTTPException(404, "知识库不存在")
    return kb

@router.delete("/{kb_id}")
async def delete_kb(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if kb:
        if await es_client.es.indices.exists(index=kb.es_index_name):
            await es_client.es.indices.delete(index=kb.es_index_name)
        await s.delete(kb); await s.commit()
    return {"ok": True}
```

- [ ] **Step 3: directory.py（目录树）**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Directory
from app.schemas import DirIn
from app.deps import get_current_user
import uuid

router = APIRouter(prefix="/api/v1", tags=["dir"])

@router.post("/knowledge-bases/{kb_id}/directories")
async def create_dir(kb_id: uuid.UUID, body: DirIn, u=Depends(get_current_user),
                     s: AsyncSession = Depends(get_session)):
    d = Directory(kb_id=kb_id, parent_id=body.parent_id, name=body.name)
    s.add(d); await s.commit(); await s.refresh(d)
    return {"id": str(d.id)}

@router.get("/knowledge-bases/{kb_id}/directories")
async def tree(kb_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Directory).where(Directory.kb_id == kb_id))).scalars().all()
    return [{"id": str(r.id), "parent_id": str(r.parent_id) if r.parent_id else None,
             "name": r.name, "sort_order": r.sort_order} for r in rows]

@router.delete("/directories/{dir_id}")
async def del_dir(dir_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Directory, dir_id)
    if d: await s.delete(d); await s.commit()
    return {"ok": True}
```

- [ ] **Step 4: ingestion.py（上传 -> MinIO -> 建文档 -> 入队）**

```python
from kb_common.clients import minio_client
from kb_common.models import Document
from datetime import datetime
import uuid, io

ALLOWED = {"pdf","doc","docx","txt","md","csv","xlsx","xls"}

async def upload_document(s, kb, file, directory_id, enqueue):
    ext = file.filename.rsplit(".",1)[-1].lower()
    if ext not in ALLOWED:
        raise ValueError(f"不支持的格式: {ext}")
    data = await file.read()
    obj_key = f"{kb.id}/{uuid.uuid4().hex}.{ext}"
    minio_client.minio.put_object(minio_client.RAW, obj_key, io.BytesIO(data), len(data))
    doc = Document(kb_id=kb.id, directory_id=directory_id, filename=obj_key,
                   original_filename=file.filename, file_type=ext, file_size=len(data),
                   storage_path=obj_key, status="PENDING")
    s.add(doc); await s.commit(); await s.refresh(doc)
    await enqueue(str(doc.id))  # 提交 Celery 任务（Task 9）
    return doc
```

- [ ] **Step 5: document.py（上传/列表/详情/切片/预览/删除/重处理）**

```python
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import Document, Segment, KnowledgeBase
from kb_common.clients import es_client, minio_client
from kb_common.config import get_settings
from app.services.ingestion import upload_document
from app.deps import get_current_user
from app.worker import process_document
import uuid, urllib.parse, base64

router = APIRouter(prefix="/api/v1", tags=["doc"])

@router.post("/documents/upload")
async def upload(kb_id: uuid.UUID = Form(...), directory_id: uuid.UUID | None = Form(None),
                 file: UploadFile = File(...), u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id) or (_ for _ in ()).throw(HTTPException(404))
    doc = await upload_document(s, kb, file, directory_id, lambda did: process_document.delay(did))
    return {"document_id": str(doc.id), "status": doc.status}

@router.get("/documents")
async def list_docs(kb_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "filename": r.original_filename, "file_type": r.file_type,
             "file_size": r.file_size, "status": r.status, "chunk_count": r.chunk_count,
             "error_message": r.error_message} for r in rows]

@router.get("/documents/{doc_id}/segments")
async def segments(doc_id: uuid.UUID, page: int = 1, size: int = 20,
                    u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    q = select(Segment).where(Segment.document_id == doc_id).order_by(Segment.chunk_index)\
        .offset((page-1)*size).limit(size)
    rows = (await s.execute(q)).scalars().all()
    return [{"chunk_index": r.chunk_index, "content": r.content, "content_hash": r.content_hash,
             "token_count": r.token_count, "page_number": r.page_number} for r in rows]

@router.get("/documents/{doc_id}/preview")
async def preview(doc_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Document, doc_id) or (_ for _ in ()).throw(HTTPException(404))
    kb = await s.get(KnowledgeBase, d.kb_id)
    # MinIO 生成临时下载 URL，base64 编码给 kkFileView
    from datetime import timedelta
    url = minio_client.minio.presigned_get_object(minio_client.RAW, d.storage_path, expires=timedelta(hours=1))
    encoded = base64.b64encode(url.encode()).decode()
    return {"preview_url": f"{get_settings().kkfv_url}/onlinePreview?url={urllib.parse.quote(encoded)}",
            "preview_type": "pdf" if d.file_type == "pdf" else "office"}

@router.delete("/documents/{doc_id}")
async def del_doc(doc_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    d = await s.get(Document, doc_id)
    if d:
        kb = await s.get(KnowledgeBase, d.kb_id)
        await es_client.delete_by_doc(kb.es_index_name, str(d.id))
        await s.delete(d); await s.commit()
    return {"ok": True}

@router.post("/documents/{doc_id}/reprocess")
async def reprocess(doc_id: uuid.UUID, u=Depends(get_current_user)):
    process_document.delay(str(doc_id))
    return {"ok": True}
```
> 注：`app.worker` 在 Task 9 创建；本任务先写 `process_document.delay(...)` 调用点并 `# noqa` 占位，Task 9 接通。为让本任务可启动，先在 `app/worker.py` 写一个 stub `process_document = type("T",(),{"delay":staticmethod(lambda *a: None)})()`。

- [ ] **Step 6: 注册路由并验证**

`main.py` 追加：
```python
from app.routes import knowledge_base, directory, document
app.include_router(knowledge_base.router)
app.include_router(directory.router)
app.include_router(document.router)
```
```bash
# 启动后：登录拿 token，创建 KB，上传一个 txt
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8000/api/v1/knowledge-bases -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"测试库","kb_type":"DOCUMENT"}'
echo "hello world, this is a test doc for RAG pipeline." > /tmp/test.txt
curl -s -X POST "localhost:8000/api/v1/documents/upload?kb_id=<上一步id>" -H "Authorization: Bearer $TOKEN" -F 'file=@/tmp/test.txt'
```
Expected: 文档创建 PENDING，MinIO raw-docs 桶出现对象。

- [ ] **Step 7: Commit**

```bash
git add services/kb-api
git commit -m "feat(kb-api): knowledge 模块 KB/目录/文档上传/切片/预览"
```

---

## Task 6: rag chunker + indexer（切片 + ES 索引 + segments 回写）

**Files:**
- Create: `services/kb-common/kb_common/rag/chunker.py`
- Create: `services/kb-common/kb_common/rag/indexer.py`
- Create: `services/kb-api/app/routes/internal.py`（追加 `/internal/index`）
- Create: `tests/test_chunker.py`

**Interfaces:**
- Consumes: `embedder.embed`、`es_client.ensure_index/bulk_index`
- Produces:
  - `chunker.chunk(text, strategy, size, overlap, delimiter) -> list[{text, page, index}]`
  - `indexer.index_document(s, kb, doc, markdown) -> int`（返回 chunk 数）

- [ ] **Step 1: chunker.py（FixedSize + Delimiter，参考 Dify FixedTokenTextSplitter）**

```python
import hashlib, re

def chunk(text: str, strategy: str = "FIXED_SIZE", size: int = 512,
          overlap: int = 150, delimiter: str | None = None) -> list[dict]:
    """返回 [{'text','chunk_index','content_hash','token_count','page_number'}]。
    - FIXED_SIZE: 按字符长度滑窗切片
    - DELIMITER: 优先按分隔符切段，超长段再按 FIXED_SIZE 兜底
    - MARKDOWN_HEADER: 按 # 标题切（MVP 近似按双换行段落 + 标题边界）
    """
    text = (text or "").strip()
    if not text: return []
    if strategy == "DELIMITER" and delimiter:
        parts = re.split(re.escape(delimiter), text)
    elif strategy == "MARKDOWN_HEADER":
        parts = re.split(r"\n(?=#{1,6}\s)", text)
    else:
        parts = [text]

    out, idx = [], 0
    for p in parts:
        p = p.strip()
        if not p: continue
        if len(p) <= size:
            _append(out, idx, p); idx += 1
        else:
            for i in range(0, len(p), size - overlap):
                seg = p[i:i+size]
                if seg.strip():
                    _append(out, idx, seg); idx += 1
                if i + size >= len(p): break
    return out

def _append(out, idx, text):
    out.append({
        "text": text,
        "chunk_index": idx,
        "content_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:32],
        "token_count": len(text),   # MVP 以字符数近似 token
        "page_number": 1,
    })
```

- [ ] **Step 2: 测试 chunker（先写测试）**

`tests/test_chunker.py`:
```python
from kb_common.rag.chunker import chunk

def test_fixed_size_basic():
    r = chunk("a"*1200, "FIXED_SIZE", size=512, overlap=150)
    assert len(r) >= 3
    assert all("text" in x and "content_hash" in x for x in r)

def test_delimiter_priority():
    r = chunk("aa\n\nbb\n\ncc", "DELIMITER", size=512, overlap=0, delimiter="\n\n")
    assert len(r) == 3 and r[0]["text"] == "aa"

def test_empty():
    assert chunk("") == []
```
```bash
uv run pytest tests/test_chunker.py -q
```
Expected: 3 passed。

- [ ] **Step 3: indexer.py（向量化 + ES bulk + segments 回写）**

```python
from kb_common.rag import embedder, chunker
from kb_common.clients import es_client
from kb_common.models import Segment
from datetime import datetime, timezone

async def index_document(s, kb, doc, markdown: str) -> int:
    """切片 -> 向量化 -> ES bulk -> 回写 segments。返回 chunk 数。"""
    chunks = chunker.chunk(markdown, kb.chunk_strategy, kb.chunk_size, kb.chunk_overlap, kb.delimiter)
    if not chunks: return 0
    texts = [c["text"] for c in chunks]
    vectors = embedder.embed(texts)   # 本地 FlagEmbedding
    index = await es_client.ensure_index(str(kb.id))

    docs = []
    segs = []
    for c, vec in zip(chunks, vectors):
        es_id = f"{doc.id}_{c['chunk_index']}"
        docs.append({
            "text": c["text"], "vector": vec,
            "kb_id": str(kb.id), "kb_type": "DOCUMENT",
            "document_id": str(doc.id), "chunk_index": c["chunk_index"],
            "total_chunks": len(chunks), "source_type": "DOCUMENT",
            "source_path": doc.storage_path, "document_title": doc.original_filename,
            "file_type": doc.file_type, "page_number": c["page_number"],
            "directory_id": str(doc.directory_id) if doc.directory_id else None,
            "directory_path": "", "content_hash": c["content_hash"],
            "token_count": c["token_count"], "created_at": datetime.now(timezone.utc).isoformat(),
        })
        segs.append(Segment(document_id=doc.id, es_chunk_id=es_id, chunk_index=c["chunk_index"],
                            content=c["text"], content_hash=c["content_hash"],
                            token_count=c["token_count"], page_number=c["page_number"]))
    await es_client.bulk_index(index, docs)
    s.add_all(segs)
    return len(chunks)
```

- [ ] **Step 4: 追加 /internal/index（同步索引入口，供 worker/同步模式调用）**

`internal.py` 追加：
```python
@router.post("/index")
async def index_doc(document_id: str, s: AsyncSession = Depends(get_session)):
    from kb_common.models import Document, KnowledgeBase
    from kb_common.rag.indexer import index_document
    from kb_common.clients import minio_client
    doc = await s.get(Document, document_id)
    kb = await s.get(KnowledgeBase, doc.kb_id)
    # 从 MinIO 取解析结果（parsed_path 优先，否则 raw）
    obj = doc.parsed_path or doc.storage_path
    from io import BytesIO
    buf = BytesIO(); minio_client.minio.get_object(minio_client.PARSED if doc.parsed_path else minio_client.RAW, obj, buf)
    markdown = buf.getvalue().decode("utf-8", errors="ignore")
    n = await index_document(s, kb, doc, markdown)
    doc.chunk_count = n; await s.commit()
    return {"chunk_count": n}
```

- [ ] **Step 5: 验证**

```bash
uv run pytest tests/test_chunker.py -q
# 手动：把 Task5 上传的 txt 触发 /internal/index（需先有 parsed，txt 走 raw 兜底）
curl -s -X POST "localhost:8000/internal/index?document_id=<doc_id>"
curl -s "localhost:9200/kb_<kbid短>/_count"
```
Expected: ES 文档数 = chunk 数。

- [ ] **Step 6: Commit**

```bash
git add services/kb-common services/kb-api tests
git commit -m "feat(rag): chunker + indexer 切片与 ES 索引"
```

---

## Task 7: rag searcher + reranker + tracer（混合检索 + RRF + 重排 + 溯源）

**Files:**
- Create: `services/kb-common/kb_common/rag/searcher.py`
- Create: `services/kb-common/kb_common/rag/tracer.py`
- Create: `services/kb-api/app/routes/search.py`
- Create: `tests/test_rrf.py`

**Interfaces:**
- Produces:
  - `searcher.hybrid(kb_ids, query, top_k, filters) -> list[dict]`（已 RRF 融合，含 BM25/kNN score）
  - `tracer.trace(hit, s) -> dict`（补全目录路径/预览链接）
  - `POST /api/v1/search`、`GET /api/v1/search/trace/{chunk_id}`、`POST /api/v1/search/test`

- [ ] **Step 1: searcher.py（kNN + BM25 + RRF，参考 Dify retrieval）**

```python
from kb_common.clients import es_client
from kb_common.rag import embedder, reranker
from elasticsearch import AsyncElasticsearch

K_RRF = 60

async def _knn(es: AsyncElasticsearch, index: str, vector, top_k: int, filters: dict):
    q = {"field": "vector", "query_vector": vector, "k": top_k, "num_candidates": top_k*5}
    if filters.get("directory_ids"):
        q["filter"] = {"terms": {"directory_id": filters["directory_ids"]}}
    r = await es.knn_search(index=index, knn=q, size=top_k,
                            source=["text","document_id","document_title","chunk_index",
                                    "page_number","source_path","file_type","content_hash",
                                    "directory_id","kb_type","faq_entry_id","faq_answer"])
    return [(h["_id"], h["_score"], h["_source"]) for h in r["hits"]["hits"]]

async def _bm25(es: AsyncElasticsearch, index: str, query: str, top_k: int, filters: dict):
    must = [{"match": {"text": query}}]
    if filters.get("directory_ids"):
        must.append({"terms": {"directory_id": filters["directory_ids"]}})
    r = await es.search(index=index, query={"bool": {"must": must}}, size=top_k,
                        source=True)
    return [(h["_id"], h["_score"], h["_source"]) for h in r["hits"]["hits"]]

def _rrf(ranklists: list[list[tuple]], top_k: int) -> list[tuple]:
    """多路结果 RRF 融合。ranklists: 每路 [(id, score, src)]，按出现顺序即排名。"""
    scores = {}
    src_map = {}
    for rl in ranklists:
        for rank, (hid, _score, src) in enumerate(rl):
            scores[hid] = scores.get(hid, 0) + 1.0 / (K_RRF + rank + 1)
            src_map[hid] = src
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [(hid, sc, src_map[hid]) for hid, sc in ordered]

async def hybrid(kb_ids: list[str], query: str, top_k: int = 10,
                 filters: dict | None = None, rerank: bool = True) -> list[dict]:
    filters = filters or {}
    qvec = embedder.embed([query])[0]
    es = es_client.es
    merged = []
    for kb_id in kb_ids:
        index = f"kb_{kb_id.replace('-', '')}"
        if not await es.indices.exists(index=index): continue
        knn = await _knn(es, index, qvec, top_k, filters)
        bm25 = await _bm25(es, index, query, top_k, filters)
        merged.append(knn); merged.append(bm25)
    fused = _rrf(merged, top_k * 5 if rerank else top_k)
    docs = [{"id": hid, "score": sc, **src} for hid, sc, src in fused]
    if rerank and docs:
        docs = reranker.rerank(query, docs, top_n=top_k)
        # rerank 后补回原始 score
    return docs[:top_k]
```

- [ ] **Step 2: 测试 RRF**

`tests/test_rrf.py`:
```python
from kb_common.rag.searcher import _rrf

def test_rrf_fuses_and_ranks():
    a = [("h1", 10, {"t":"a"}), ("h2", 9, {"t":"b"}), ("h3", 8, {"t":"c"})]
    b = [("h2", 10, {"t":"b"}), ("h1", 9, {"t":"a"}), ("h4", 8, {"t":"d"})]
    r = _rrf([a, b], top_k=4)
    ids = [x[0] for x in r]
    assert ids[0] in ("h1", "h2")   # 两路都靠前，融合后置顶
    assert "h4" in ids and "h3" in ids
```
```bash
uv run pytest tests/test_rrf.py -q
```
Expected: 1 passed。

- [ ] **Step 3: tracer.py（溯源字段组装）**

```python
from urllib.parse import quote
import base64
from kb_common.config import get_settings
from kb_common.clients import minio_client
from datetime import timedelta

def trace(hit: dict, doc_map: dict) -> dict:
    """hit: 检索结果；doc_map: {document_id: (original_filename, storage_path, file_type)}"""
    doc_id = hit.get("document_id")
    fname, path, ftype = doc_map.get(doc_id, (hit.get("document_title"), hit.get("source_path"), hit.get("file_type")))
    preview_type = "pdf" if ftype == "pdf" else ("image" if ftype in ("jpg","png","jpeg") else "office")
    try:
        url = minio_client.minio.presigned_get_object(minio_client.RAW, path, expires=timedelta(hours=1))
        encoded = base64.b64encode(url.encode()).decode()
        preview_url = f"{get_settings().kkfv_url}/onlinePreview?url={quote(encoded)}"
    except Exception:
        preview_url = None
    return {
        "chunk_id": hit.get("id"),
        "text": hit.get("text"),
        "score": hit.get("rerank_score", hit.get("score")),
        "source_type": hit.get("kb_type") or "DOCUMENT",
        "document_id": doc_id,
        "document_title": fname,
        "page_number": hit.get("page_number"),
        "chunk_index": hit.get("chunk_index"),
        "directory_path": hit.get("directory_path") or "",
        "source_path": path,
        "preview_url": preview_url,
        "preview_type": preview_type,
        "content_hash": hit.get("content_hash"),
        "faq_answer": hit.get("faq_answer"),
    }
```

- [ ] **Step 4: search.py 路由**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session
from kb_common.models import Document
from kb_common.rag import searcher, tracer
from app.deps import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["search"])

class SearchIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 10
    search_type: str = "hybrid"   # hybrid | semantic | keyword
    filters: dict | None = None

@router.post("")
async def search(body: SearchIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    hits = await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    results = [tracer.trace(h, dmap) for h in hits]
    return {"results": results, "total": len(results)}

@router.post("/test")
async def search_test(body: SearchIn, u=Depends(get_current_user)):
    """检索测试：返回召回内容、K 值、Score，便于调参。"""
    hits = await searcher.hybrid(body.kb_ids, body.query, body.top_k, body.filters, rerank=False)
    return {"k": body.top_k, "results": [{"text": h.get("text"), "score": h.get("score"),
            "document_title": h.get("document_title"), "chunk_index": h.get("chunk_index")} for h in hits]}
```

- [ ] **Step 5: 注册并验证**

```bash
# main.py 追加 from app.routes import search; app.include_router(search.router)
uv run pytest tests/test_rrf.py -q
# 手动检索
curl -s -X POST localhost:8000/api/v1/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"test","kb_ids":["<kb_id>"],"top_k":5}' | python3 -m json.tool
```
Expected: 返回带 `score`、`document_title`、`preview_url`、`content_hash` 的结果。

- [ ] **Step 6: Commit**

```bash
git add services/kb-common services/kb-api tests
git commit -m "feat(rag): 混合检索 kNN+BM25+RRF + rerank + 溯源"
```

---

## Task 8: rag LLM 问答（RAG 生成 + 引用溯源）

**Files:**
- Create: `services/kb-api/app/services/chat.py`
- Create: `services/kb-api/app/routes/search.py`（追加 `/api/v1/chat`）
- Create: `services/kb-api/app/routes/settings_route.py`（模型配置读写，覆盖 .env）

**Interfaces:**
- Consumes: `searcher.hybrid`、`llm_client.chat`、`Setting` 表
- Produces: `POST /api/v1/chat` -> `{answer, citations[]}`

- [ ] **Step 1: settings_route.py（运行时模型配置，前端可改）**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session
from kb_common.models import Setting
from app.deps import require_role
from kb_common.config import get_settings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# 可配置项白名单（is_secret=true 的只回显 key，不回显 value）
KEYS = {
    "llm_base_url": ("LLM 服务地址", False),
    "llm_api_key": ("LLM API Key", True),
    "llm_model": ("LLM 模型名", False),
    "mineru_api_key": ("MinerU API Key", True),
}

@router.get("")
async def get_settings_api(u=Depends(require_role("super_admin","admin")),
                           s: AsyncSession = Depends(get_session)):
    out = {}
    for k, (label, secret) in KEYS.items():
        row = (await s.execute(select(Setting).where(Setting.key == k))).scalar_one_or_none()
        val = row.value if row else getattr(get_settings(), k, "")
        out[k] = {"label": label, "value": "" if (secret and val) else val,
                  "is_set": bool(val), "is_secret": secret}
    return out

class SettingIn(BaseModel):
    key: str
    value: str

@router.put("")
async def set_settings_api(body: SettingIn, u=Depends(require_role("super_admin","admin")),
                           s: AsyncSession = Depends(get_session)):
    if body.key not in KEYS: 
        from fastapi import HTTPException; raise HTTPException(400, "不支持的配置项")
    secret = KEYS[body.key][1]
    row = (await s.execute(select(Setting).where(Setting.key == body.key))).scalar_one_or_none()
    if row: row.value = body.value
    else: s.add(Setting(key=body.key, value=body.value, is_secret=secret))
    await s.commit()
    return {"ok": True}
```

- [ ] **Step 2: chat.py（检索 -> 拼 prompt -> LLM 生成 -> 带引用）**

```python
from kb_common.rag import searcher, tracer
from kb_common.clients import llm_client
from kb_common.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.models import Document, Setting
import json

SYS_PROMPT = "你是一个严谨的知识库问答助手。只根据下方【参考资料】回答问题。"
TMPL = """【参考资料】
{ctx}

【问题】{q}

要求：
1. 仅依据参考资料作答，不要编造。
2. 在答案末尾用 [1][2]... 标注引用的资料编号。
3. 资料不足时回答"根据现有知识库无法回答"。
"""

async def _effective(s: AsyncSession, key: str) -> str:
    row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or getattr(get_settings(), key)

async def answer(query: str, kb_ids: list[str], top_k: int, s: AsyncSession) -> dict:
    hits = await searcher.hybrid(kb_ids, query, top_k, rerank=True)
    doc_ids = {h.get("document_id") for h in hits if h.get("document_id")}
    docs = (await s.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    dmap = {str(d.id): (d.original_filename, d.storage_path, d.file_type) for d in docs}
    cited = [tracer.trace(h, dmap) for h in hits]

    ctx = "\n\n".join(f"[{i+1}] ({c['document_title']} p.{c['page_number']})\n{c['text']}"
                      for i, c in enumerate(cited)) or "（无相关资料）"
    messages = [{"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": TMPL.format(ctx=ctx, q=query)}]
    base_url = await _effective(s, "llm_base_url")
    api_key = await _effective(s, "llm_api_key")
    model = await _effective(s, "llm_model")
    try:
        ans = await llm_client.chat(messages, model=model, base_url=base_url, api_key=api_key)
    except Exception as e:
        ans = f"（LLM 调用失败：{e}。请在 设置 页配置 LLM API Key。）"
    return {"answer": ans, "citations": cited}
```

- [ ] **Step 3: search.py 追加 /chat**

```python
class ChatIn(BaseModel):
    query: str
    kb_ids: list[str]
    top_k: int = 5

@router.post("/chat")
async def chat(body: ChatIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    from app.services.chat import answer
    return await answer(body.query, body.kb_ids, body.top_k, s)
```

- [ ] **Step 4: 注册 settings 路由并验证**

```bash
# main.py 追加 from app.routes import settings_route; app.include_router(settings_route.router)
# 手动：配置 LLM key 后问答
curl -s -X PUT localhost:8000/api/v1/settings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"key":"llm_api_key","value":"<your-glm-key>"}'
curl -s -X POST localhost:8000/api/v1/search/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"test","kb_ids":["<kb_id>"],"top_k":3}' | python3 -m json.tool
```
Expected: 返回 `answer`（含 [1] 标注）+ `citations`。未配 key 时返回友好提示。

- [ ] **Step 5: Commit**

```bash
git add services/kb-api
git commit -m "feat(rag): LLM RAG 问答 + 引用溯源 + 模型配置接口"
```

---

## Task 9: kb-worker 异步采集流水线（MinerU 解析 -> 切片 -> 向量化 -> 索引）

**Files:**
- Create: `services/kb-api/app/worker.py`（Celery app + `process_document` 任务）
- Modify: `services/kb-api/app/services/ingestion.py`（真实 `enqueue` 接通）

**Interfaces:**
- Consumes: `mineru_client.parse`、`indexer.index_document`、`minio_client`
- Produces: `process_document.delay(doc_id)`；文档状态机 PENDING->PARSING->...->COMPLETED|FAILED。

- [ ] **Step 1: worker.py（Celery app + 状态机 + 失败重试）**

```python
from celery import Celery
from sqlalchemy import select
from kb_common.config import get_settings
from kb_common.database import SessionLocal
from kb_common.models import Document, KnowledgeBase, Setting
from kb_common.clients import minio_client, mineru_client
from kb_common.rag.indexer import index_document
from io import BytesIO

s = get_settings()
celery_app = Celery("kb", broker=s.redis_url, backend=s.redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True,
                       task_default_queue="ingestion",
                       autoretry_for=(Exception,), retry_backoff=True,
                       retry_kwargs={"max_retries": 3})

async def _setting(session, key, default=""):
    row = (await session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return (row.value if row else None) or default or getattr(s, key)

@celery_app.task(name="process_document", bind=True)
def process_document(self, doc_id: str):
    import asyncio
    asyncio.run(_run(doc_id))

async def _run(doc_id: str):
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
        if not doc: return
        kb = await s.get(KnowledgeBase, doc.kb_id)
        try:
            # 1. PARSING：取原文件 -> MinerU 解析 -> 存 parsed
            doc.status = "PARSING"; await s.commit()
            buf = BytesIO()
            minio_client.minio.get_object(minio_client.RAW, doc.storage_path, buf)
            raw = buf.getvalue()
            api_key = await _setting(s, "mineru_api_key")
            parsed = await mineru_client.parse(raw, doc.original_filename, api_key=api_key)
            markdown = parsed["markdown"]
            pkey = f"{kb.id}/{doc.id}.md"
            minio_client.minio.put_object(minio_client.PARSED, pkey, BytesIO(markdown.encode()), len(markdown))
            doc.parsed_path = pkey

            # 2-4. CHUNKING/EMBEDDING/INDEXING：index_document 内完成（含 embed）
            doc.status = "INDEXING"; await s.commit()
            n = await index_document(s, kb, doc, markdown)

            doc.chunk_count = n; doc.status = "COMPLETED"; doc.error_message = None
            await s.commit()
        except Exception as e:
            doc.status = "FAILED"; doc.error_message = str(e)[:500]; await s.commit()
            raise   # 触发 Celery 重试（autoretry）
```

- [ ] **Step 2: 接通 ingestion.enqueue**

`ingestion.py` 的 `upload_document` 已调用 `process_document.delay(...)`；移除 Task 5 的 stub，改为 `from app.worker import process_document`。worker 模块在 import 时不触发 Celery 连接（lazy），kb-api 进程 import 安全。

- [ ] **Step 3: 启动 worker 并端到端验证**

```bash
# 终端1：api
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
# 终端2：worker
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion -l info
# 终端3：上传 txt（走本地兜底解析，无需 MinerU key）
curl -s -X POST "localhost:8000/api/v1/documents/upload?kb_id=<kb_id>" -H "Authorization: Bearer $TOKEN" -F 'file=@/tmp/test.txt'
# 轮询状态
curl -s "localhost:8000/api/v1/documents?kb_id=<kb_id>" -H "Authorization: Bearer $TOKEN"
```
Expected: 状态从 PENDING -> PARSING -> INDEXING -> COMPLETED；`chunk_count > 0`；ES 有文档。

- [ ] **Step 4: 失败重试验证（可选）**

上传一个未支持格式或空 MinerU key 的 pdf，观察 status=FAILED + error_message，且 Celery 日志显示重试。

- [ ] **Step 5: Commit**

```bash
git add services/kb-api
git commit -m "feat(worker): Celery 异步采集流水线 MinerU->切片->向量化->索引"
```

---

## Task 10: faq-service 独立服务（FAQ KB + 目录 + 条目 + 批量导入 + FAQ 检索 + 溯源）

**Files:**
- Create: `services/faq-service/pyproject.toml`、`Dockerfile`
- Create: `services/faq-service/app/main.py`、`deps.py`、`schemas.py`
- Create: `services/faq-service/app/routes/{kb,directory,entry,search}.py`
- Create: `services/faq-service/app/services/{faq_import,faq_index,faq_search}.py`

**Interfaces:**
- Consumes: `kb_common.*`（models/db/security/es_client/minio）、kb-api `/internal/embed`（HTTP，避免重复加载模型）
- Produces: FAQ 全套 API；JWT 自验（与 kb-api 共享密钥）；FAQ 写入 ES（`source_type=FAQ`）。

**设计要点（避免 BGE 模型二次加载）：** faq-service 不本地加载 FlagEmbedding，而是 HTTP 调 kb-api `/internal/embed` 获取向量；ES 直接读写（共享基础设施）；FAQ 检索 = PG 关键字精准匹配 + ES kNN 语义，精准置顶、去重，不经过 reranker。

- [ ] **Step 1: 依赖与 main**

`services/faq-service/pyproject.toml`:
```toml
[project]
name = "faq-service"
version = "0.1.0"
requires-python = ">=3.11,<3.12"
dependencies = ["kb-common", "uvicorn[standard]>=0.29", "openpyxl>=3.1"]
[tool.uv.sources]
kb-common = { path = "../kb-common", editable = true }
```
`app/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import kb, directory, entry, search
app = FastAPI(title="FAQ Service")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for r in (kb.router, directory.router, entry.router, search.router):
    app.include_router(r)

@app.get("/health")
def health(): return {"status": "ok"}
```

- [ ] **Step 2: deps.py（JWT 自验）**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kb_common.database import get_session
from kb_common.security import decode_jwt
from kb_common.models import User

bearer = HTTPBearer()

async def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                           s: AsyncSession = Depends(get_session)) -> User:
    try:
        payload = decode_jwt(cred.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效凭证")
    u = await s.get(User, payload["sub"])
    if not u or not u.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    return u
```

- [ ] **Step 3: kb.py + directory.py（与 knowledge 同构，kb_type=FAQ，用 FaqDirectory）**

```python
# routes/kb.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import KnowledgeBase
from kb_common.clients import es_client
from app.deps import get_current_user
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq/knowledge-bases", tags=["faq-kb"])

class KbIn(BaseModel):
    name: str
    description: str | None = None

@router.post("")
async def create_kb(body: KbIn, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = KnowledgeBase(name=body.name, description=body.description, kb_type="FAQ",
                       owner_id=u.id, es_index_name=f"kb_{uuid.uuid4().hex}",
                       chunk_strategy="FIXED_SIZE")
    s.add(kb); await s.commit(); await s.refresh(kb)
    await es_client.ensure_index(str(kb.id))
    return {"id": str(kb.id), "name": kb.name}

@router.get("")
async def list_kb(u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(KnowledgeBase).where(KnowledgeBase.kb_type == "FAQ"))).scalars().all()
    return [{"id": str(r.id), "name": r.name, "description": r.description} for r in rows]
```
`routes/directory.py`：同 Task 5 directory.py，但操作 `FaqDirectory`，路径前缀 `/api/v1/faq`。

- [ ] **Step 4: faq_index.py（调 kb-api embed + 写 ES）**

```python
import httpx
from kb_common.clients import es_client
from kb_common.config import get_settings
from datetime import datetime, timezone

async def _embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{s.kb_api_internal_url}/internal/embed", json={"texts": texts})
        r.raise_for_status()
        return r.json()["vectors"]

async def index_entry(kb, entry):
    vec = (await _embed([entry.question]))[0]
    index = await es_client.ensure_index(str(kb.id))
    doc = {
        "text": entry.question, "vector": vec,
        "kb_id": str(kb.id), "kb_type": "FAQ",
        "faq_entry_id": str(entry.id), "source_type": "FAQ",
        "document_title": entry.question, "faq_answer": entry.answer,
        "directory_id": str(entry.directory_id) if entry.directory_id else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await es_client.es.index(index=index, id=f"faq_{entry.id}", document=doc, refresh=True)

async def delete_entry(kb_id, entry_id):
    index = f"kb_{kb_id.replace('-', '')}"
    if await es_client.es.indices.exists(index=index):
        try: await es_client.es.delete(index=index, id=f"faq_{entry_id}", refresh=True)
        except Exception: pass
```

- [ ] **Step 5: entry.py（CRUD + 批量导入）**

```python
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from kb_common.models import FaqEntry, KnowledgeBase
from app.deps import get_current_user
from app.services import faq_index, faq_import
import uuid
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/faq", tags=["faq-entry"])

class EntryIn(BaseModel):
    question: str
    answer: str
    keywords: list[str] = []
    directory_id: uuid.UUID | None = None

@router.post("/knowledge-bases/{kb_id}/entries")
async def create(kb_id: uuid.UUID, body: EntryIn, u=Depends(get_current_user),
                 s: AsyncSession = Depends(get_session)):
    e = FaqEntry(kb_id=kb_id, directory_id=body.directory_id, question=body.question,
                 answer=body.answer, keywords=body.keywords, status="DRAFT")
    s.add(e); await s.commit(); await s.refresh(e)
    kb = await s.get(KnowledgeBase, kb_id)
    await faq_index.index_entry(kb, e)
    e.status = "INDEXED"; await s.commit()
    return {"id": str(e.id), "status": "INDEXED"}

@router.get("/knowledge-bases/{kb_id}/entries")
async def list_(kb_id: uuid.UUID, keyword: str = "", u=Depends(get_current_user),
                s: AsyncSession = Depends(get_session)):
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    if keyword:
        q = q.where(FaqEntry.question.ilike(f"%{keyword}%"))
    rows = (await s.execute(q.order_by(FaqEntry.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "question": r.question, "answer": r.answer,
             "keywords": r.keywords, "status": r.status} for r in rows]

@router.delete("/entries/{entry_id}")
async def delete(entry_id: uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    e = await s.get(FaqEntry, entry_id)
    if e:
        await faq_index.delete_entry(str(e.kb_id), str(e.id))
        await s.delete(e); await s.commit()
    return {"ok": True}

@router.post("/knowledge-bases/{kb_id}/entries/batch")
async def batch(kb_id: uuid.UUID, file: UploadFile = File(...), u=Depends(get_current_user),
                s: AsyncSession = Depends(get_session)):
    rows = await faq_import.parse(file)   # [{question, answer, keywords[]}]
    kb = await s.get(KnowledgeBase, kb_id)
    cnt = 0
    for r in rows:
        e = FaqEntry(kb_id=kb_id, question=r["question"], answer=r["answer"],
                     keywords=r.get("keywords", []), status="DRAFT")
        s.add(e); await s.commit(); await s.refresh(e)
        try: await faq_index.index_entry(kb, e); e.status = "INDEXED"
        except Exception: e.status = "FAILED"
        await s.commit(); cnt += 1
    return {"imported": cnt}
```

- [ ] **Step 6: faq_import.py（CSV/Excel 解析）**

```python
import io, csv
from openpyxl import load_workbook

async def parse(file) -> list[dict]:
    data = await file.read()
    name = file.filename.lower()
    if name.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        return [_row(r) for r in reader]
    if name.endswith((".xlsx", ".xls")):
        wb = load_workbook(io.BytesIO(data)); ws = wb.active
        headers = [c.value for c in ws[1]]
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            rec = dict(zip(headers, row)); out.append(_row(rec))
        return out
    raise ValueError("仅支持 csv/xlsx")

def _row(r: dict) -> dict:
    q = (r.get("question") or r.get("问题") or "").strip()
    a = (r.get("answer") or r.get("答案") or "").strip()
    kw = (r.get("keywords") or r.get("关键词") or "").strip()
    return {"question": q, "answer": a,
            "keywords": [k.strip() for k in kw.split(",") if k.strip()] if kw else []}
```

- [ ] **Step 7: faq_search.py + search.py（精准匹配 + 语义 + 溯源）**

```python
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.models import FaqEntry, Document
from kb_common.clients import es_client
from kb_common.config import get_settings
from app.services.faq_index import _embed

async def search(s: AsyncSession, kb_id: str, query: str, top_k: int = 5) -> dict:
    # 1. PG 关键字精准匹配（question/keywords）
    q = select(FaqEntry).where(FaqEntry.kb_id == kb_id)
    q = q.where(FaqEntry.question.ilike(f"%{query}%"))
    precise = (await s.execute(q.limit(top_k))).scalars().all()

    # 2. ES kNN 语义（FAQ 类型）
    qvec = (await _embed([query]))[0]
    index = f"kb_{kb_id.replace('-', '')}"
    sem = []
    if await es_client.es.indices.exists(index=index):
        r = await es_client.es.knn_search(index=index, knn={
            "field": "vector", "query_vector": qvec, "k": top_k,
            "num_candidates": top_k*5, "filter": {"term": {"kb_type": "FAQ"}}}, size=top_k)
        sem = r["hits"]["hits"]

    # 3. 融合：精准置顶 + 语义补充（按 entry_id 去重）
    seen, results = set(), []
    for e in precise:
        seen.add(str(e.id))
        results.append({"entry_id": str(e.id), "question": e.question, "answer": e.answer,
                        "score": 1.0, "match_type": "precise",
                        "source_document_id": str(e.source_document_id) if e.source_document_id else None})
    for h in sem:
        src = h["_source"]
        eid = src.get("faq_entry_id")
        if eid in seen: continue
        seen.add(eid)
        results.append({"entry_id": eid, "question": src.get("text"), "answer": src.get("faq_answer"),
                        "score": h["_score"], "match_type": "semantic",
                        "source_document_id": src.get("document_id")})
        if len(results) >= top_k: break
    return {"results": results[:top_k], "total": len(results)}
```
`routes/search.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from kb_common.database import get_session
from app.deps import get_current_user
from app.services import faq_search
import uuid

router = APIRouter(prefix="/api/v1/faq/search", tags=["faq-search"])

class Q(BaseModel):
    kb_id: str
    query: str
    top_k: int = 5

@router.post("")
async def do(body: Q, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    return await faq_search.search(s, body.kb_id, body.query, body.top_k)
```

- [ ] **Step 8: 验证**

```bash
cd services/faq-service && uv run uvicorn app.main:app --reload --port 8004
# 确保 kb-api 也在跑（提供 /internal/embed）
TOKEN=<同 kb-api 的 token>
curl -s -X POST localhost:8004/api/v1/faq/knowledge-bases -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"FAQ测试"}'
curl -s -X POST localhost:8004/api/v1/faq/knowledge-bases/<id>/entries -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"question":"如何重置密码","answer":"点击登录页忘记密码","keywords":["密码","重置"]}'
curl -s -X POST localhost:8004/api/v1/faq/search -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"kb_id":"<id>","query":"密码忘了"}'
```
Expected: 检索返回该 FAQ，`match_type=precise` 或 `semantic`。

- [ ] **Step 9: Commit**

```bash
git add services/faq-service
git commit -m "feat(faq): 独立 FAQ 服务 CRUD+批量导入+检索+溯源"
```

---

## Task 11: 前端接真实后端 + 模型配置页 + RAG 问答页

**Files:**
- Reuse: `docs/superpowers/plans/2026-07-29-frontend-plan.md`（Task 1-10 的脚手架/布局/登录/KB/文档/FAQ/检索页面）
- Modify: `web/vite.config.ts`（proxy `/api/v1` -> kb-api:8000，`/api/v1/faq` -> faq-service:8004）
- Modify: `web/.env`（`VITE_USE_MOCK=false`）
- Create: `web/src/views/settings/index.vue`（模型配置页）
- Create: `web/src/views/chat/index.vue`（RAG 问答页）
- Create: `web/src/api/settings.ts`、`web/src/api/chat.ts`

**Interfaces:**
- Consumes: kb-api `/api/v1/*`、faq-service `/api/v1/faq/*`、kb-api `/api/v1/settings`、`/api/v1/search/chat`

- [ ] **Step 1: 按前端计划搭起骨架与核心页**

执行 `2026-07-29-frontend-plan.md` 的 Task 1-4（脚手架/路由/布局/登录）、Task 6-7（知识库/文档/切片）、Task 9（FAQ）、Task 10（检索+溯源），得到可运行的前端（MSW mock 模式）。

- [ ] **Step 2: 切真实后端 + 代理分流**

`web/vite.config.ts` dev server proxy：
```ts
server: {
  proxy: {
    '/api/v1/faq': { target: 'http://localhost:8004', changeOrigin: true },
    '/api/v1':     { target: 'http://localhost:8000', changeOrigin: true },
  }
}
```
`web/.env`：`VITE_USE_MOCK=false`（保留 MSW 以便回退）。`api/request.ts` 的 baseURL 保持 `''`（走代理）。

- [ ] **Step 3: 模型配置页（GLM/DeepSeek + MinerU key）**

`web/src/api/settings.ts`：
```ts
import request from './request'
export const getSettings = () => request.get('/api/v1/settings')
export const setSetting = (data: { key: string; value: string }) => request.put('/api/v1/settings', data)
```
`web/src/views/settings/index.vue`（el-form）：
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getSettings, setSetting } from '@/api/settings'
import { ElMessage } from 'element-plus'
const form = ref<Record<string, any>>({})
const providers = [
  { label: 'GLM (智谱)', url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { label: 'DeepSeek', url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
]
onMounted(async () => { form.value = (await getSettings()).data })
const save = async (k: string) => { await setSetting({ key: k, value: form.value[k].value }); ElMessage.success('已保存') }
const pick = (p: any) => { form.value.llm_base_url.value = p.url; form.value.llm_model.value = p.model }
</script>
<template>
  <el-card>
    <template #header>模型配置</template>
    <el-form label-width="140px">
      <el-divider>LLM 大模型</el-divider>
      <el-form-item label="快速选择">
        <el-button v-for="p in providers" :key="p.label" @click="pick(p)">{{ p.label }}</el-button>
      </el-form-item>
      <el-form-item label="LLM 服务地址"><el-input v-model="form.llm_base_url?.value" />
        <el-button type="primary" @click="save('llm_base_url')">保存</el-button></el-form-item>
      <el-form-item label="LLM API Key"><el-input v-model="form.llm_api_key?.value" show-password placeholder="未设置" />
        <el-button type="primary" @click="save('llm_api_key')">保存</el-button></el-form-item>
      <el-form-item label="模型名"><el-input v-model="form.llm_model?.value" />
        <el-button type="primary" @click="save('llm_model')">保存</el-button></el-form-item>
      <el-divider>文档解析</el-divider>
      <el-form-item label="MinerU API Key"><el-input v-model="form.mineru_api_key?.value" show-password placeholder="未设置" />
        <el-button type="primary" @click="save('mineru_api_key')">保存</el-button></el-form-item>
      <el-alert type="info" :closable="false" title="向量模型 BGE-M3 与重排模型 BGE-reranker 本地部署，无需配置。" />
    </el-form>
  </el-card>
</template>
```
路由追加 `/settings`（仅 admin+）。

- [ ] **Step 4: RAG 问答页（检索 + 生成 + 引用）**

`web/src/api/chat.ts`：
```ts
import request from './request'
export const chat = (data: { query: string; kb_ids: string[]; top_k?: number }) =>
  request.post('/api/v1/search/chat', data)
```
`web/src/views/chat/index.vue`：输入框 + 知识库多选 + 「提问」按钮 -> 展示 `answer`（markdown）+ `citations`（点击展开溯源：文档名/页码/切片/预览按钮）。复用 `SearchTraceDrawer` 组件展示引用详情。

- [ ] **Step 5: 端到端联调验证**

```bash
# 三个后端 + 前端都起来
cd services/kb-api && uv run uvicorn app.main:app --port 8000 &
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion -l info &
cd services/faq-service && uv run uvicorn app.main:app --port 8004 &
cd web && pnpm dev
```
浏览器：登录 -> 设置页配 LLM key -> 知识库页建库 -> 上传 txt -> 等待 COMPLETED -> 检索页查到结果 + 溯源 -> 问答页提问得带引用答案。

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat(web): 接真实后端 + 模型配置页 + RAG 问答页"
```

---

## Task 12: docker-compose 一键 + 端到端冒烟 + README

**Files:**
- Modify: `docker-compose.app.yml`（补 kb-api/faq-service/worker 的 env 覆盖 + depends_on）
- Create: `scripts/smoke_test.sh`
- Create: `README.md`

- [ ] **Step 1: 完善 docker-compose.app.yml（Docker 全量模式）**

补 `.env.docker`（容器内用服务名连基础设施）：
```env
DATABASE_URL=postgresql+asyncpg://dev:dev123456@dev-postgres:5432/dev_db
REDIS_URL=redis://:dev123456@dev-redis:6379/0
ES_HOST=http://dev-elasticsearch:9200
MINIO_ENDPOINT=dev-minio:9000
KKFV_URL=http://dev-kkfileview:8012
KB_API_INTERNAL_URL=http://kb-api:8000
```
> Docker 模式下 BGE 模型在 kb-api 容器内 CPU 推理，需 colima 至少 8GB：`colima stop && colima start --cpu 4 --memory 8`。MVP 推荐用「本地原生运行 + Docker 基础设施」的开发模式（见各 Task 验证步骤）。

- [ ] **Step 2: 冒烟测试脚本**

`scripts/smoke_test.sh`：
```bash
#!/usr/bin/env bash
set -e
BASE=http://localhost:8000
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
H="Authorization: Bearer $TOKEN"

echo "[1/5] 创建知识库"; KB=$(curl -s -X POST $BASE/api/v1/knowledge-bases -H "$H" -H 'Content-Type: application/json' -d '{"name":"冒烟库"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "hello RAG smoke test." > /tmp/s.txt
echo "[2/5] 上传文档"; curl -s -X POST "$BASE/api/v1/documents/upload?kb_id=$KB" -H "$H" -F 'file=@/tmp/s.txt' >/dev/null
echo "[3/5] 等待处理"; for i in $(seq 1 20); do ST=$(curl -s "$BASE/api/v1/documents?kb_id=$KB" -H "$H" | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['status'])"); echo "  -> $ST"; [ "$ST" = "COMPLETED" ] && break; [ "$ST" = "FAILED" ] && exit 1; sleep 2; done
echo "[4/5] 检索"; curl -s -X POST $BASE/api/v1/search -H "$H" -H 'Content-Type: application/json' -d "{\"query\":\"RAG\",\"kb_ids\":[\"$KB\"],\"top_k\":3}" | python3 -m json.tool
echo "[5/5] 问答（需配 LLM key）"; curl -s -X POST $BASE/api/v1/search/chat -H "$H" -H 'Content-Type: application/json' -d "{\"query\":\"RAG\",\"kb_ids\":[\"$KB\"],\"top_k\":3}" | python3 -m json.tool
echo "SMOKE OK"
```
```bash
chmod +x scripts/smoke_test.sh && ./scripts/smoke_test.sh
```
Expected: `SMOKE OK`（问答步骤在未配 LLM key 时返回友好提示，不阻断冒烟）。

- [ ] **Step 3: README**

覆盖：架构图（3 进程 + 基础设施）、本地开发启动顺序（infra -> kb-api -> worker -> faq-service -> web）、`.env` 配置说明、Docker 一键 `docker compose -f docker-compose.app.yml up -d`、冒烟脚本、常见问题（MinerU/LLM key 配置、colima 内存）。

- [ ] **Step 4: Commit**

```bash
git add docker-compose.app.yml scripts/smoke_test.sh README.md .env.docker
git commit -m "feat(deploy): docker-compose 一键 + 冒烟测试 + README"
```

---

## Self-Review（计划自检）

**1. Spec 覆盖（P0 = 原 6 项 MVP 跑通）：**
| MVP 需求 | 覆盖 Task |
|----------|-----------|
| 文档采集与解析（多格式） | Task 3（MinerU 客户端）+ Task 5（上传）+ Task 9（解析流水线） |
| 基础切片与 RAG | Task 6（chunker+indexer）+ Task 7（检索+重排） |
| FAQ 知识库 | Task 10（独立 faq-service） |
| 基础检索（语义+关键字+混合） | Task 7（kNN+BM25+RRF） |
| 权限管理与目录管理 | Task 4（auth+RBAC）+ Task 5（目录树） |
| 检索结果溯源 | Task 7（tracer）+ ES 溯源字段 |
| LLM 问答（用户确认纳入） | Task 8（RAG 生成+引用） |

**2. 占位符扫描：** MinerU 云 API 的确切请求/轮询流程在 Task 3 标注「Task 9 按官方文档补全」并提供了 txt/md/csv 本地兜底，保证流水线可先跑通；无其他 TBD/TODO。

**3. 类型一致：** `embedder.embed -> list[list[float]]`（1024 维）在 Task 3/6/7/10 一致；`searcher.hybrid -> list[dict]` 在 Task 7/8 一致；`tracer.trace -> dict` 字段与前端 SearchTraceDrawer/引用展示对齐；`process_document.delay(doc_id)` 在 Task 5 调用、Task 9 定义，签名一致。

**4. 架构一致：** 3 进程（kb-api / faq-service / kb-worker）与用户决策一致；BGE 模型仅在 kb-api 加载一次，faq-service/worker 经 `/internal/embed` 复用，避免 Mac 内存爆炸。

**5. 风险点（已标注）：**
- FlagEmbedding 首次加载慢（下载 ~2GB 模型），首次 `uv sync` 与首次 embed 较慢。
- MinerU 云 API 需 Task 9 接官方文档；MVP 先 txt/md/csv 兜底。
- colima 4GB 不足以 Docker 模式装模型 -> 开发期本地原生运行，Docker 模式需 8GB。

## Execution Handoff

计划已写入 `docs/superpowers/plans/2026-07-29-mvp-pipeline-plan.md`。两种执行方式：

**1. Subagent-Driven（推荐）** — 每个 Task 派发独立 subagent，Task 1-9 串行（有依赖），Task 10 与 Task 11 可并行，Task 12 收尾。任务间有 review 检查点。

**2. Inline Execution** — 在当前会话按 Task 顺序批量执行，每 2-3 个 Task 一个检查点。

**建议选择 1**：后端涉及 ES/FlagEmbedding/Celery 多组件，subagent 隔离执行 + review 能更快定位环境问题。你倾向哪种方式？
