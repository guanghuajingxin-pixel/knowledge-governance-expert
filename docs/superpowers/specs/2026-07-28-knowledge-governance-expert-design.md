# Knowledge Governance Expert — Technical Design

> **Date:** 2026-07-28
> **Status:** Draft
> **Architecture:** Microservices (5 services + 7 infrastructure components)

## Overview

以 Dify 知识库内核为参考，构建独立的知识库系统。MVP 阶段实现文档采集解析、切片与检索增强、FAQ 知识库、混合检索、权限管理、检索结果溯源 6 项核心能力。

## Tech Stack

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI (Python 3.11+) | 异步、自动 OpenAPI 文档 |
| 异步任务 | Celery + Redis | 文档解析和索引为异步流水线 |
| 关系型数据库 | PostgreSQL 16 + pgvector | 元数据存储，预留向量检索能力 |
| 搜索引擎 | Elasticsearch 8.15 | kNN 向量检索 + BM25 全文检索 |
| 对象存储 | MinIO | 原始文件、解析结果、预览文件 |
| 文档解析 | MinerU | 多格式文档解析（PDF/Word/PPT/Excel/Markdown 等） |
| Embedding | BGE-M3 (via TEI) | 1024 维，多语言，支持稠密+稀疏向量 |
| Reranker | BGE-reranker-v2-m3 (via TEI) | 检索结果重排序 |
| 文件预览 | kkFileView | 20+ 格式在线预览 |
| 前端 | Vue 3 + TypeScript + Element Plus | 管理后台（经典 Admin 布局） |
| 预览 | kkFileView | 20+ 格式在线预览 |
| 图标 | Element Plus Icons / @element-plus/icons-vue | 统一图标库 |
| 部署 | Docker Compose | 一键启动所有服务 |
| 参考代码 | Dify (main 分支) | 架构设计参考，不直接依赖 |

## Service Architecture

```
                    ┌──────────────────────────────────────────┐
                    │              api-gateway :8080            │
                    │     (认证 · 鉴权 · 路由 · 限流 · CORS)     │
                    └───┬──────┬──────┬──────┬─────────────────┘
                        │      │      │      │
             ┌──────────┤ ┌────┤  ┌───┤ ┌────┤
             ▼          │ ▼    │  ▼   │ ▼    │
   ┌─────────────┐     │┌──────────┐│┌──────────┐┌─────────────┐
   │auth-service │     ││knowledge-│││faq-      ││ rag-service │
   │   :8001     │     ││service   │││service   ││   :8003     │
   │             │     ││  :8002   │││  :8004   ││             │
   │ 用户管理     │     ││          │││          ││ 切片引擎     │
   │ 角色权限 RBAC│     ││文档KB CRUD││FAQ KB CRUD││ BGE-M3 嵌入 │
   │ API Key     │     ││目录管理   │││Q&A 管理   ││ ES 索引管理  │
   │ JWT 签发    │     ││文档管理   │││批量导入   ││ kNN+BM25检索 │
   └──────┬──────┘     ││采集编排   │││FAQ检索    ││ BGE-reranker │
          │            ││预览服务   │││关联溯源   ││ 结果溯源     │
          │            │└────┬─────┘│└────┬─────┘└──────┬──────┘
          │            │     │      │     │             │
          ▼            ▼     ▼      ▼     ▼             ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                         基础设施层                             │
   │  PostgreSQL:5432 │ ES:9200 │ MinIO:9000 │ Redis:6379         │
   │  MinerU:8001 │ BGE-M3:8002 │ BGE-reranker:8003 │ kkFileView:8012 │
   └──────────────────────────────────────────────────────────────┘
```

### Service Responsibilities

| 服务 | 端口 | 职责 | 数据主权 | 对外暴露 |
|------|------|------|----------|----------|
| **api-gateway** | 8080 | 统一入口、JWT 验证、RBAC 中间件、请求路由、CORS、限流、健康检查聚合 | 无状态 | ✓ |
| **auth-service** | 8001 | 用户注册/登录、角色管理（super_admin/admin/editor/viewer）、API Key 生成/验证、JWT 签发 | PG `users` `roles` `api_keys` | 通过 gateway |
| **knowledge-service** | 8002 | 文档型知识库 CRUD、目录树管理、文档上传/状态追踪、采集流水线编排（MinerU → RAG）、kkFileView 预览 | PG `knowledge_bases`(DOCUMENT) `directories` `documents` `segments` | 通过 gateway |
| **faq-service** | 8004 | FAQ 型知识库 CRUD、FAQ 目录管理、Q&A 对 CRUD、CSV/Excel 批量导入、FAQ 专属检索策略（精准匹配优先） | PG `knowledge_bases`(FAQ) `faq_directories` `faq_entries` `segments`(FAQ) | 通过 gateway |
| **rag-service** | 8003 | 切片引擎、BGE-M3 向量化、ES 索引管理、混合检索（kNN + BM25 + RRF 融合）、BGE-reranker 重排序、溯源信息组装 | ES 全部索引 | 仅内部 |

### Async Workers

| Worker | Queue | 职责 |
|--------|-------|------|
| knowledge-worker | `ingestion` | 调用 MinerU 解析文档、存储解析结果、编排下游索引任务 |
| rag-worker | `indexing` | 执行切片 → 向量化 → ES 索引写入流水线 |

## Data Model

### PostgreSQL Tables

#### auth-service 管辖

```
users:
  id (UUID PK), username (VARCHAR(100) UNIQUE), password_hash (VARCHAR(256)),
  email (VARCHAR(200)), role (VARCHAR(20): super_admin|admin|editor|viewer),
  is_active (BOOLEAN), created_at, updated_at

api_keys:
  id (UUID PK), user_id (FK→users), name (VARCHAR(100)),
  key_hash (VARCHAR(64) UNIQUE), key_prefix (VARCHAR(10)),
  is_active (BOOLEAN), last_used_at, created_at
```

#### knowledge-service 管辖

```
knowledge_bases:
  id (UUID PK), name (VARCHAR(200)), description (TEXT),
  kb_type (VARCHAR(20): DOCUMENT|FAQ), owner_id (FK→users),
  chunk_strategy (VARCHAR(30): FIXED_SIZE|PARAGRAPH|MARKDOWN_HEADER|SENTENCE),
  chunk_size (INT, default=512), chunk_overlap (INT, default=150),
  embedding_model (VARCHAR(100), default='bge-m3'),
  es_index_name (VARCHAR(100) UNIQUE), created_at, updated_at

directories:
  id (UUID PK), kb_id (FK→knowledge_bases), parent_id (FK self, nullable),
  name (VARCHAR(200)), sort_order (INT), created_at

documents:
  id (UUID PK), kb_id (FK→knowledge_bases), directory_id (FK→directories, nullable),
  filename (VARCHAR(500)), original_filename (VARCHAR(500)),
  file_type (VARCHAR(20)), file_size (BIGINT),
  storage_path (VARCHAR(1000)),    -- MinIO 原始文件 key
  parsed_path (VARCHAR(1000)),     -- MinIO 解析结果 key
  status (VARCHAR(20): PENDING→PARSING→CHUNKING→EMBEDDING→INDEXING→COMPLETED|FAILED),
  chunk_count (INT), error_message (TEXT),
  created_at, updated_at

segments:
  id (UUID PK), document_id (FK→documents), faq_entry_id (FK→faq_entries, nullable),
  es_chunk_id (VARCHAR(100)), chunk_index (INT),
  content (TEXT), content_hash (VARCHAR(64)),
  token_count (INT), embedding_dim (INT), created_at
```

#### faq-service 管辖

```
faq_directories:
  id (UUID PK), kb_id (FK→knowledge_bases), parent_id (FK self, nullable),
  name (VARCHAR(200)), sort_order (INT), created_at

faq_entries:
  id (UUID PK), kb_id (FK→knowledge_bases), directory_id (FK→faq_directories, nullable),
  question (TEXT), answer (TEXT), keywords (TEXT[]),
  source_document_id (FK→documents, nullable),   -- 溯源关联
  category_tags (TEXT[]),
  view_count (INT), helpful_count (INT),
  status (VARCHAR(20): DRAFT|PENDING|INDEXED|FAILED),
  created_at, updated_at
```

### Elasticsearch Index Mapping

每个知识库一个独立索引，命名规则 `kb_{kb_id}`：

```json
{
  "kb_{kb_id}": {
    "mappings": {
      "properties": {
        "text":           { "type": "text", "analyzer": "standard" },
        "vector":         { "type": "dense_vector", "dims": 1024, "similarity": "cosine" },

        "kb_id":          { "type": "keyword" },
        "kb_type":        { "type": "keyword" },
        "document_id":    { "type": "keyword" },
        "faq_entry_id":   { "type": "keyword" },
        "chunk_index":    { "type": "integer" },
        "total_chunks":   { "type": "integer" },
        "source_type":    { "type": "keyword" },
        "source_path":    { "type": "keyword" },
        "document_title": { "type": "text", "fields": {"raw": {"type": "keyword"}} },
        "file_type":      { "type": "keyword" },
        "page_number":    { "type": "integer" },
        "directory_id":   { "type": "keyword" },
        "directory_path": { "type": "text" },
        "faq_answer":     { "type": "text" },

        "preview_url":    { "type": "keyword" },
        "preview_type":   { "type": "keyword" },

        "content_hash":   { "type": "keyword" },
        "token_count":    { "type": "integer" },
        "created_at":     { "type": "date" }
      }
    }
  }
}
```

**溯源字段说明：**

| 字段 | 用途 | 前端展示示例 |
|------|------|-------------|
| `document_title` | 源文件名 | "《产品手册 v3.2.pdf》" |
| `page_number` | 所在页码 | "第 12 页" |
| `directory_path` | 目录全路径 | "技术文档 / API 参考 / 认证" |
| `source_type` | 来源类型 | "文档检索" / "FAQ匹配" |
| `source_path` | MinIO 对象 key | 点击下载原文件 |
| `content_hash` | 切片 SHA256 | 校验完整性 |
| `preview_url` | kkFileView 预览链接 | 在线预览原文件 |
| `preview_type` | 预览类型 | `pdf` / `office` / `image` |

## Processing Pipelines

### 文档处理流水线（异步）

```
POST /api/v1/documents/upload
  │
  ▼
knowledge-service (同步)
  ├─ 1. 存入 MinIO (bucket: raw-docs)
  ├─ 2. 创建 document 记录 (status=PENDING)
  ├─ 3. 提交 Celery 任务到 ingestion queue
  └─ 4. 返回 {document_id, job_id, status: "PENDING"}
  
  
Celery Worker: knowledge-worker (ingestion queue)
  ├─ 1. 更新 status → PARSING
  ├─ 2. 调用 MinerU API: POST /parse {file_path}
  ├─ 3. 存储解析结果到 MinIO (bucket: parsed-docs)
  ├─ 4. 从 kb 配置读取切片策略
  ├─ 5. 调用 rag-service: POST /internal/index
  │      {kb_id, document_id, segments: [{text, chunk_index, metadata{}}]}
  └─ 6. 更新 document.status → PROCESSING (等待 rag 完成)
  
  
Celery Worker: rag-worker (indexing queue)
  ├─ 1. 执行切片策略 (FixedSize/Paragraph/Markdown/Sentence)
  ├─ 2. 调用 BGE-M3 API 批量向量化 (batch=32)
  ├─ 3. 创建/确保 ES 索引存在
  ├─ 4. 批量写入 ES (Bulk API)
  ├─ 5. 回写 segments 表 (chunk_index, es_chunk_id, content_hash)
  └─ 6. 回调 knowledge-service /faq-service 更新 status → COMPLETED
```

### FAQ 处理流水线

```
POST /api/v1/faq/knowledge-bases/{id}/entries
  │
  ▼
faq-service (同步)
  ├─ 1. 创建 faq_entry 记录 (status=DRAFT)
  ├─ 2. 提交 Celery 任务
  └─ 3. 返回 {entry_id, status}
  
  
Celery Worker (faq-indexing, 复用 rag-worker)
  ├─ 1. 构建 Document 对象 (page_content=question, metadata={answer})
  ├─ 2. BGE-M3 embed(question) → 存入向量
  ├─ 3. ES 索引写入 (source_type=FAQ, text=question, faq_answer=answer)
  └─ 4. 更新 faq_entry.status → INDEXED
```

### 检索流程（同步）

```
POST /api/v1/search
  {query, kb_ids[], top_k, search_type: "hybrid"|"semantic"|"keyword"|"faq"}
  │
  ▼
knowledge-service / faq-service
  │
  ├─ 校验权限 (用户对 kb_ids 的访问权限)
  │
  ├─ 调用 rag-service: POST /internal/search
  │     {kb_ids[], query, top_k, filters{}}
  │     │
  │     ├─ 1. BGE-M3 embed(query) → query_vector (1024-dim)
  │     ├─ 2. ES kNN search: cosine similarity on vector field
  │     ├─ 3. ES BM25 search: full-text on text field
  │     ├─ 4. RRF 融合 (k=60): score = Σ 1/(k+rank_i)
  │     ├─ 5. BGE-reranker: 取 top_n=融合结果前50，重排序
  │     └─ 6. 返回 SearchResult[] + 溯源元数据
  │
  └─ 附加目录路径、格式化 MinIO 下载链接、返回
```

FAQ 检索在 faq-service 内部额外做一步精准匹配：

```
FAQ 查询 → faq-service
  ├─ 1. PG 关键字精准匹配: SELECT * WHERE keywords @> ARRAY['term']
  ├─ 2. rag-service 语义检索 (同上)
  ├─ 3. 融合: 精准匹配结果置顶，语义结果补充
  └─ 4. 返回 {entry_id, question, answer, source_document_id, score}
```

## API Design

### External API (via api-gateway :8080)

#### 认证

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/login` | 登录，返回 JWT |
| POST | `/api/v1/auth/register` | 注册 |
| GET | `/api/v1/users/me` | 当前用户信息 |

#### API Key 管理

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/api-keys` | 创建 API Key（返回原始 key，仅此一次） |
| GET | `/api/v1/auth/api-keys` | 列出当前用户的 API Keys |
| DELETE | `/api/v1/auth/api-keys/{id}` | 注销 API Key |

#### 知识库（文档型）

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/knowledge-bases` | 创建知识库 |
| GET | `/api/v1/knowledge-bases` | 列出知识库（支持分页、筛选） |
| GET | `/api/v1/knowledge-bases/{id}` | 知识库详情 |
| PUT | `/api/v1/knowledge-bases/{id}` | 更新配置（切片策略、参数） |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库（级联删除文档、索引） |

#### 目录管理

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/knowledge-bases/{id}/directories` | 创建目录 |
| GET | `/api/v1/knowledge-bases/{id}/directories` | 目录树 |
| PUT | `/api/v1/directories/{id}` | 重命名/移动目录 |
| DELETE | `/api/v1/directories/{id}` | 删除目录 |

#### 文档管理

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/documents/upload` | 上传文档（multipart/form-data: file, kb_id, directory_id） |
| GET | `/api/v1/documents` | 文档列表（?kb_id=&directory_id=&status=&page=&size=） |
| GET | `/api/v1/documents/{id}` | 文档详情 + 处理状态 |
| DELETE | `/api/v1/documents/{id}` | 删除文档（级联删除 segments + ES 索引） |
| GET | `/api/v1/documents/{id}/preview` | kkFileView 在线预览 |
| GET | `/api/v1/documents/{id}/segments` | 文档切片列表（?page=&size=） |
| POST | `/api/v1/documents/{id}/reprocess` | 重新处理文档 |

#### FAQ 知识库

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/faq/knowledge-bases` | 创建 FAQ 知识库 |
| GET | `/api/v1/faq/knowledge-bases` | FAQ 知识库列表 |
| GET | `/api/v1/faq/knowledge-bases/{id}` | FAQ 知识库详情 |
| DELETE | `/api/v1/faq/knowledge-bases/{id}` | 删除 FAQ 知识库 |

#### FAQ 目录

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/faq/knowledge-bases/{id}/directories` | 创建 FAQ 目录 |
| GET | `/api/v1/faq/knowledge-bases/{id}/directories` | FAQ 目录树 |
| PUT | `/api/v1/faq/directories/{id}` | 更新目录 |
| DELETE | `/api/v1/faq/directories/{id}` | 删除目录 |

#### FAQ 条目

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/faq/knowledge-bases/{id}/entries` | 新增 Q&A |
| POST | `/api/v1/faq/knowledge-bases/{id}/entries/batch` | 批量导入（CSV/Excel） |
| GET | `/api/v1/faq/knowledge-bases/{id}/entries` | Q&A 列表（?directory_id=&status=&keyword=&page=&size=） |
| PUT | `/api/v1/faq/entries/{id}` | 更新 Q&A |
| DELETE | `/api/v1/faq/entries/{id}` | 删除 Q&A |

#### 检索

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/search` | 统一检索 `{query, kb_ids[], top_k, search_type}` |
| GET | `/api/v1/search/trace/{chunk_id}` | 检索结果溯源详情 |

检索请求体：
```json
{
  "query": "如何配置 OAuth2 认证",
  "kb_ids": ["uuid-1", "uuid-2"],
  "top_k": 10,
  "search_type": "hybrid",
  "filters": {
    "directory_ids": ["uuid-dir-1"],
    "file_types": ["pdf", "markdown"]
  }
}
```

检索响应体：
```json
{
  "results": [
    {
      "chunk_id": "es-chunk-uuid",
      "text": "配置 OAuth2 需要在应用设置中...",
      "score": 0.92,
      "source_type": "DOCUMENT",
      "document_id": "doc-uuid",
      "document_title": "系统配置指南 v2.1.pdf",
      "page_number": 12,
      "total_chunks": 45,
      "directory_path": "技术文档 / 认证配置",
      "source_path": "https://minio:9000/raw-docs/abc123.pdf",
      "preview_url": "http://kkfileview:8012/onlinePreview?url=...",
      "preview_type": "pdf",
      "content_hash": "sha256:abc..."
    }
  ],
  "total": 10,
  "took_ms": 145
}
```

### Internal API（服务间通信，不对外暴露）

#### rag-service

| Method | Path | Description |
|--------|------|-------------|
| POST | `/internal/index` | 提交索引任务到 `indexing` queue |
| POST | `/internal/index/faq` | 提交 FAQ 索引任务 |
| DELETE | `/internal/index/{kb_id}/documents/{doc_id}` | 删除文档所有 ES 索引 |
| POST | `/internal/search` | 执行检索 |
| GET | `/internal/search/trace/{chunk_id}` | 获取溯源详情 |
| GET | `/internal/health` | 服务健康检查 |

## Deployment

### Docker Compose Services

| Service | Image | Port | Resources |
|---------|-------|------|-----------|
| postgres | `pgvector/pgvector:pg16` | 5432 | 1 CPU, 1GB RAM |
| elasticsearch | `elasticsearch:8.15.0` | 9200 | 2 CPU, 2GB RAM |
| minio | `minio/minio:latest` | 9000, 9001 | 1 CPU, 512MB RAM |
| redis | `redis:7-alpine` | 6379 | 0.5 CPU, 256MB RAM |
| mineru | `opendatalab/mineru:latest` | 8001 | 2 CPU, 4GB RAM, GPU optional |
| bge-m3 | `ghcr.io/huggingface/text-embeddings-inference:latest` | 8002 | GPU (recommended) |
| bge-reranker | `ghcr.io/huggingface/text-embeddings-inference:latest` | 8003 | GPU (recommended) |
| kkfileview | `keking/kkfileview:latest` | 8012 | 1 CPU, 1GB RAM |
| api-gateway | custom build | 8080 | 0.5 CPU, 256MB RAM |
| auth-service | custom build | 8001 | 0.5 CPU, 256MB RAM |
| knowledge-service | custom build | 8002 | 0.5 CPU, 512MB RAM |
| knowledge-worker | custom build (celery) | — | 1 CPU, 1GB RAM |
| faq-service | custom build | 8004 | 0.5 CPU, 256MB RAM |
| rag-service | custom build | 8003 | 1 CPU, 1GB RAM |
| rag-worker | custom build (celery) | — | 1 CPU, 1GB RAM |

### 完整 docker-compose.yml

```yaml
version: '3.8'
services:
  # ===== 基础设施 =====
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: knowledge_base
      POSTGRES_USER: kb_user
      POSTGRES_PASSWORD: kb_pass
    ports: ["5432:5432"]
    volumes: [pg_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "kb_user"]
      interval: 5s
      retries: 10

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.15.0
    environment:
      discovery.type: single-node
      xpack.security.enabled: false
      ES_JAVA_OPTS: "-Xms2g -Xmx2g"
    ports: ["9200:9200"]
    volumes: [es_data:/usr/share/elasticsearch/data]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9200"]
      interval: 10s
      retries: 10

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  mineru:
    image: opendatalab/mineru:latest
    ports: ["8001:8001"]
    volumes: [minio_data:/data]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  bge-m3:
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    command: --model-id BAAI/bge-m3 --port 80
    ports: ["8002:80"]
    volumes: [model_cache:/data]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  bge-reranker:
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    command: --model-id BAAI/bge-reranker-v2-m3 --port 80
    ports: ["8003:80"]
    volumes: [model_cache:/data]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  kkfileview:
    image: keking/kkfileview:latest
    ports: ["8012:8012"]
    environment:
      OFFICE_PREVIEW_TYPE: pdf

  # ===== 业务服务 =====
  api-gateway:
    build: ./services/api-gateway
    ports: ["8080:8080"]
    depends_on:
      - auth-service
      - knowledge-service
      - faq-service
      - rag-service
    environment:
      AUTH_SERVICE_URL: http://auth-service:8001
      KNOWLEDGE_SERVICE_URL: http://knowledge-service:8002
      FAQ_SERVICE_URL: http://faq-service:8004
      RAG_SERVICE_URL: http://rag-service:8003
      JWT_SECRET: ${JWT_SECRET}

  auth-service:
    build: ./services/auth-service
    ports: ["8001:8001"]
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://kb_user:kb_pass@postgres:5432/knowledge_base
      JWT_SECRET: ${JWT_SECRET}

  knowledge-service:
    build: ./services/knowledge-service
    ports: ["8002:8002"]
    depends_on:
      postgres: { condition: service_healthy }
      minio: { condition: service_started }
      redis: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://kb_user:kb_pass@postgres:5432/knowledge_base
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      MINERU_URL: http://mineru:8001
      KKFV_URL: http://kkfileview:8012
      RAG_SERVICE_URL: http://rag-service:8003
      CELERY_BROKER_URL: redis://redis:6379/0

  knowledge-worker:
    build: ./services/knowledge-service
    command: celery -A app.worker worker -Q ingestion --concurrency=4
    depends_on: [redis, knowledge-service]
    environment:
      DATABASE_URL: postgresql+asyncpg://kb_user:kb_pass@postgres:5432/knowledge_base
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      MINERU_URL: http://mineru:8001
      RAG_SERVICE_URL: http://rag-service:8003
      CELERY_BROKER_URL: redis://redis:6379/0

  faq-service:
    build: ./services/faq-service
    ports: ["8004:8004"]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+asyncpg://kb_user:kb_pass@postgres:5432/knowledge_base
      RAG_SERVICE_URL: http://rag-service:8003
      CELERY_BROKER_URL: redis://redis:6379/0

  rag-service:
    build: ./services/rag-service
    ports: ["8003:8003"]
    depends_on:
      elasticsearch: { condition: service_started }
      bge-m3: { condition: service_started }
      redis: { condition: service_healthy }
    environment:
      ES_HOST: http://elasticsearch:9200
      BGE_M3_URL: http://bge-m3:80/embed
      BGE_RERANKER_URL: http://bge-reranker:80/rerank
      CELERY_BROKER_URL: redis://redis:6379/0

  rag-worker:
    build: ./services/rag-service
    command: celery -A app.worker worker -Q indexing --concurrency=2
    depends_on: [redis, rag-service]
    environment:
      ES_HOST: http://elasticsearch:9200
      BGE_M3_URL: http://bge-m3:80/embed
      CELERY_BROKER_URL: redis://redis:6379/0

volumes:
  pg_data:
  es_data:
  minio_data:
  model_cache:
```

## Project Structure

```
knowledge-base/
├── docker-compose.yml
├── .env
├── CLAUDE.md
├── dify/                              # Dify 源码（架构参考）
│   └── ...
├── services/
│   ├── api-gateway/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py                # FastAPI + httpx 路由代理
│   │       ├── middleware/
│   │       │   ├── auth.py            # JWT 验证中间件
│   │       │   └── rbac.py            # RBAC 权限检查中间件
│   │       └── proxy/
│   │           └── router.py          # 请求转发 + 响应聚合
│   │
│   ├── auth-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── database.py            # SQLAlchemy async engine
│   │       ├── models.py              # User, ApiKey
│   │       ├── schemas.py             # Pydantic request/response
│   │       ├── routes.py
│   │       ├── services.py
│   │       └── migrations/
│   │
│   ├── knowledge-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── database.py
│   │       ├── models.py              # KnowledgeBase, Directory, Document, Segment
│   │       ├── schemas.py
│   │       ├── routes/
│   │       │   ├── kb.py
│   │       │   ├── directory.py
│   │       │   └── document.py
│   │       ├── services/
│   │       │   ├── ingestion.py       # 上传 → MinIO → MinerU
│   │       │   ├── pipeline.py        # 编排索引任务
│   │       │   └── preview.py         # kkFileView 预览 URL 生成
│   │       ├── clients/
│   │       │   ├── mineru_client.py   # MinerU API 客户端
│   │       │   ├── minio_client.py    # MinIO 客户端封装
│   │       │   └── rag_client.py     # rag-service 内部 API 客户端
│   │       ├── worker.py              # Celery app + ingestion 任务
│   │       └── migrations/
│   │
│   ├── faq-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── database.py
│   │       ├── models.py              # FaqKnowledgeBase, FaqDirectory, FaqEntry
│   │       ├── schemas.py
│   │       ├── routes/
│   │       │   ├── kb.py
│   │       │   ├── directory.py
│   │       │   └── entry.py
│   │       ├── services/
│   │       │   ├── faq_import.py      # CSV/Excel 批量导入
│   │       │   └── faq_search.py      # FAQ 精准匹配 + 语义检索融合
│   │       ├── clients/
│   │       │   └── rag_client.py
│   │       ├── worker.py              # Celery app + faq-indexing 任务
│   │       └── migrations/
│   │
│   └── rag-service/
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           ├── main.py
│           ├── config.py
│           ├── routes/
│           │   └── internal.py         # 内部 API（仅服务间调用）
│           ├── services/
│           │   ├── chunker.py          # ChunkStrategy 抽象 + 4 种实现
│           │   ├── embedder.py         # BGE-M3 via TEI API
│           │   ├── indexer.py          # ES 索引管理
│           │   ├── searcher.py         # kNN + BM25 + RRF 融合
│           │   ├── reranker.py         # BGE-reranker via TEI API
│           │   └── tracer.py           # 溯源信息组装
│           ├── clients/
│           │   ├── es_client.py        # Elasticsearch 客户端
│           │   └── tei_client.py       # TEI API 客户端
│           ├── worker.py               # Celery app + indexing 任务
│           └── migrations/             # ES 索引模板管理
│
└── web/                                # Vue 3 管理后台（后续任务）
    └── ...
```

## Key Design Decisions

| 决策 | 选择 | 理由 |
|------|------|------|
| BGE 模型部署 | TEI (HuggingFace) | 官方推理引擎，GPU 加速，高吞吐 |
| 异步任务框架 | Celery + Redis | Python 生态标准，Dify 同方案 |
| 混合检索融合算法 | RRF (k=60) | 无需调参，kNN 和 BM25 公平融合 |
| Embedding 策略 | rag-service 内存暂存，批量写 ES | batch=32，减少 ES 请求次数 |
| 检索通信 | 同步 REST | 检索要求低延迟 |
| 索引通信 | 异步 Redis Queue | 索引可容忍延迟，解耦服务 |
| 文件预览 | kkFileView | 统一格式预览，支持 20+ 文件类型 |
| API 认证 | JWT (用户) + API Key (程序) | 双通道认证，适应不同场景 |
| 数据库迁移 | Alembic | SQLAlchemy 标准，各服务独立迁移 |
| ES 索引命名 | `kb_{kb_id}` | 每个知识库独立索引，隔离性好 |
| GPU 依赖 | BGE 模型 GPU 推荐，MinerU GPU optional | CPU 降级可用但性能差 |

## Dify 参考映射

本项目架构与 Dify 核心模块的对应关系，便于开发时快速参考：

| Dify 模块 | 本项目对应 | 参考程度 |
|-----------|-----------|----------|
| `core/rag/extractor/` | knowledge-service MinerU 调用 | 文件类型识别逻辑 |
| `core/rag/splitter/` | rag-service chunker.py | 切片策略实现 |
| `core/rag/embedding/` | rag-service embedder.py | 缓存嵌入、token 计数 |
| `core/rag/datasource/vdb/` | rag-service indexer.py + es_client.py | 向量存储抽象模式 |
| `core/rag/retrieval/` | rag-service searcher.py | 检索方法组合 |
| `core/rag/rerank/` | rag-service reranker.py | 重排序工厂模式 |
| `core/indexing_runner.py` | rag-service worker.py | 索引流水线编排 |
| `models/dataset.py` | knowledge-service models.py | 数据模型设计 |
| `services/dataset_service.py` | knowledge-service services/ | 业务逻辑 |
| `tasks/document_indexing_task.py` | knowledge-worker | 异步任务 |

## Frontend Design — Vue 3 管理后台

### 设计系统约束（风格参考）

基于参考截图，前端严格遵循以下约束：

#### 布局

```
┌─────────────────────────────────────────────────────────┐
│  Sidebar (dark, 220px)    │  Main Content (#f5f7fa)      │
│                           │                               │
│  Logo "知识库"             │  Breadcrumb / Title Row       │
│  ─────────────            │  ─────────────────────────── │
│  ○ 工作台                  │  [Action Buttons]             │
│  ● 知识库  ← active        │                               │
│  ○ 问答库                  │  ┌─────────────────────┐     │
│  ○ 数据分析                 │  │ Content Area         │     │
│  ○ 知识图谱                 │  │ (Cards / Table)      │     │
│  ○ 平台管理                 │  │                      │     │
│                           │  └─────────────────────┘     │
│                           │                               │
│  Collapse ◀               │  Pagination                  │
└─────────────────────────────────────────────────────────┘
```

#### 配色方案

| Token | 值 | 用途 |
|-------|-----|------|
| `--color-primary` | `#409EFF` | 主按钮、链接、选中态 |
| `--color-primary-light` | `#ecf5ff` | 选中行背景、tag 浅底 |
| `--color-sidebar-bg` | `#001529` / `#263445`(Element Plus dark) | 左侧导航 |
| `--color-content-bg` | `#f5f7fa` | 主内容区底色 |
| `--color-card-bg` | `#ffffff` | 卡片、表格底色 |
| `--color-success` | `#67c23a` | 状态「运行中」「正常」 |
| `--color-warning` | `#e6a23c` | 状态「索引中」「处理中」 |
| `--color-danger` | `#f56c6c` | 删除按钮、状态「失败」「已删除」 |
| `--color-info` | `#909399` | 次要文字、提示 |
| `--color-text-primary` | `#303133` | 标题、正文 |
| `--color-text-regular` | `#606266` | 描述文字 |
| `--color-text-secondary` | `#909399` | 辅助文字 |
| `--color-border` | `#dcdfe6` | 边框、分割线 |

#### 组件使用规范

| 页面 | 核心组件 | 布局方式 |
|------|----------|----------|
| 知识库概览 | `el-card` + `el-row/el-col` 栅格 | 卡片网格，每行 3-4 个 |
| 知识库详情(文档列表) | `el-table` + `el-pagination` | 表格 + 顶栏搜索/操作区 |
| 文档切片预览 | `el-tabs` + `el-tag` + `el-switch` | Tab 页签切换文档，列表展示切片 |
| FAQ 问答明细 | `el-table` + `el-popover` 行内编辑 | 表格 + 行内答案编辑弹窗 |
| 检索结果 | `el-table` + `el-tag` + `el-drawer`(溯源) | 表格 + 侧滑溯源详情 |
| 知识库创建/编辑 | `el-dialog` + `el-form` | 弹窗表单 |
| 目录管理 | `el-tree` | 树形控件 |

#### Element Plus 主题配置

```scss
// element-plus 主题覆盖 (使用 SCSS/CSS 变量)
:root {
  --el-color-primary: #409EFF;
  --el-menu-dark-bg-color: #263445;
}
```

#### 交互规范

- **主操作按钮**：`type="primary"` 实心蓝底，如「添加知识库」「上传文档」「保存」
- **次要操作**：`type="default"` 或 `link` 文字蓝，如「查看详情」「编辑」「查看」
- **危险操作**：`type="danger"` 或 `link` 文字红，如「删除」
- **状态标签**：使用 `el-tag` 区分状态，`success` = 已完成/正常，`warning` = 处理中，`danger` = 失败，`info` = 草稿
- **表格操作列**：操作项最多显示 3 个，超过放入 `el-dropdown`
- **空状态**：列表/卡片无数据时展示 `el-empty` 组件
- **加载态**：表格/卡片区域使用 `v-loading` 指令
- **消息反馈**：增删改操作使用 `ElMessage.success/error()`

### 页面路由结构

```
/                           → 重定向到 /dashboard
/dashboard                  → 工作台（首页统计）
/knowledge-bases            → 知识库卡片概览
/knowledge-bases/:id        → 文档列表 + 目录树
/knowledge-bases/:id/documents/:docId  → 文档切片预览
/faq                        → FAQ 知识库列表
/faq/:id                    → FAQ 问答明细
/search                     → 统一检索页
/admin/users                → 用户管理（admin+）
/admin/api-keys             → API Key 管理
/login                      → 登录页
```

### 前端技术选型

| 类别 | 选择 | 说明 |
|------|------|------|
| 框架 | Vue 3.4+ (Composition API + `<script setup>`) | |
| 语言 | TypeScript | 严格模式 |
| UI 组件库 | Element Plus 2.x | 与参考风格完全一致 |
| 图标库 | `@element-plus/icons-vue` | 统一图标 |
| 构建工具 | Vite 5.x | |
| 路由 | Vue Router 4.x | |
| 状态管理 | Pinia | 用户信息、知识库列表缓存 |
| HTTP 客户端 | Axios | 拦截器统一注入 JWT |
| 表格/表单 | Element Plus `el-table` / `el-form` | |
| 代码规范 | ESLint + Prettier | |

### web/ 目录结构

```
web/
├── Dockerfile
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/
│   │   └── index.ts                # 路由定义
│   ├── stores/
│   │   ├── user.ts                 # 用户状态
│   │   └── app.ts                  # 全局应用状态（侧边栏折叠等）
│   ├── api/
│   │   ├── request.ts              # Axios 实例 + 拦截器
│   │   ├── auth.ts                 # 认证 API
│   │   ├── knowledge-base.ts       # 知识库 API
│   │   ├── document.ts             # 文档 API
│   │   ├── faq.ts                  # FAQ API
│   │   └── search.ts               # 检索 API
│   ├── views/
│   │   ├── login/
│   │   │   └── index.vue
│   │   ├── dashboard/
│   │   │   └── index.vue
│   │   ├── knowledge-base/
│   │   │   ├── index.vue           # 卡片网格概览
│   │   │   ├── detail.vue          # 文档列表 + 目录树
│   │   │   └── document-preview.vue # 切片预览
│   │   ├── faq/
│   │   │   ├── index.vue           # FAQ 知识库列表
│   │   │   └── detail.vue          # 问答明细
│   │   ├── search/
│   │   │   └── index.vue           # 统一检索
│   │   └── admin/
│   │       ├── users.vue
│   │       └── api-keys.vue
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppLayout.vue       # 整体布局容器
│   │   │   ├── Sidebar.vue         # 左侧导航
│   │   │   └── Header.vue          # 顶栏（面包屑 + 用户头像）
│   │   ├── kb/
│   │   │   ├── KbCard.vue          # 知识库卡片
│   │   │   └── DirectoryTree.vue   # 目录树组件
│   │   └── common/
│   │       ├── StatusTag.vue       # 状态标签
│   │       └── SearchTrace.vue     # 溯源抽屉
│   └── styles/
│       ├── variables.scss          # Element Plus 主题变量覆盖
│       └── global.scss             # 全局样式
```

## Spec Self-Review

- **Placeholder scan**: 无 TBD/TODO，所有技术选型已明确
- **Internal consistency**: 数据模型、API、流水线与服务职责一致；ES 索引字段与溯源需求对齐；前端路由与后端 API 一一对应；Element Plus 组件选择与参考截图风格匹配
- **Scope check**: 聚焦 MVP 6 项功能，FAQ 独立服务、kkFileView 预览、溯源、前端管理后台均已覆盖
- **Ambiguity check**: 检索请求/响应已明确定义 schema；服务间通信协议明确（内部 REST + Redis Queue）；前端配色/布局/组件使用有精确约束
- **Frontend constraints**: 风格参考 `风格参考/` 目录 5 张截图，配色和布局约束写入 CLAUDE.md
