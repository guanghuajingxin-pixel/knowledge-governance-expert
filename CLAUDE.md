# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Start all services (infrastructure + microservices)
docker compose up -d

# Start infrastructure only (for local development)
docker compose up -d postgres elasticsearch minio redis

# Build a specific service
docker compose build knowledge-service

# View logs for a specific service
docker compose logs -f rag-service

# Run database migrations for a service
docker compose run --rm knowledge-service alembic upgrade head

# Access service shells
docker compose exec knowledge-service bash

# Start frontend dev server
cd web && pnpm dev

# Build frontend
cd web && pnpm build

# Python: run tests for a single service
cd services/rag-service && pytest

# Python: run tests with coverage
cd services/knowledge-service && pytest --cov=app
```

## Architecture

**Microservices** — 5 FastAPI services + 7 infrastructure components, Docker Compose orchestration. Reference: Dify source code in `dify/` directory (not a runtime dependency).

### Service Map

```
api-gateway (:8080)   — 统一入口, JWT + API Key 认证, RBAC, 路由转发
    ├── auth-service (:8001)       — 用户 CRUD, 角色管理, API Key
    ├── knowledge-service (:8002)  — 文档型 KB, 目录树, 文档上传, MinerU 解析编排
    ├── faq-service (:8004)        — FAQ 型 KB, Q&A 对管理, 批量导入, FAQ 精准匹配
    └── rag-service (:8003)        — 切片, BGE-M3 向量化, ES 索引, kNN+BM25 检索, reranker

Workers (Celery):
    knowledge-worker (queue: ingestion) — 调用 MinerU, 存储解析结果, 编排索引任务
    rag-worker (queue: indexing)       — 切片 → 向量化 → ES 索引写入
```

### Processing Pipeline

```
Upload doc → knowledge-service (MinIO + MinerU)
    → Redis Queue (ingestion)
        → knowledge-worker (parse)
            → Redis Queue (indexing)
                → rag-worker (chunk → embed → ES index)
                    → doc.status = COMPLETED
```

### Data Ownership

| Service | PostgreSQL Tables | Other Data |
|---------|------------------|------------|
| auth-service | `users`, `api_keys` | — |
| knowledge-service | `knowledge_bases`(DOCUMENT), `directories`, `documents`, `segments` | MinIO (raw-docs, parsed-docs) |
| faq-service | `knowledge_bases`(FAQ), `faq_directories`, `faq_entries` | — |
| rag-service | reads `segments` | ES indices (`kb_{kb_id}`) |

## Frontend Design System

**Tech stack:** Vue 3.4+ (Composition API + `<script setup>`), TypeScript strict, Element Plus 2.x, Vite 5.x, Pinia, Vue Router 4, Axios, `@element-plus/icons-vue`.

### Layout Pattern

Left sidebar (dark, 220px, `--el-menu-dark-bg-color: #263445`) + main content area (light gray, `#f5f7fa`). Navigation: 工作台 / 知识库 / 问答库 / 平台管理. Content area has breadcrumb row at top, action buttons below breadcrumb, then card-grid or table.

### Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `--el-color-primary` | `#409EFF` | Primary buttons, links, active states |
| `--el-color-primary-light-9` | `#ecf5ff` | Selected row background, tag light background |
| `--el-color-success` | `#67c23a` | Status: 运行中/正常/COMPLETED |
| `--el-color-warning` | `#e6a23c` | Status: 索引中/处理中/PROCESSING |
| `--el-color-danger` | `#f56c6c` | Delete buttons, status: 失败/已删除/FAILED |
| `--el-color-info` | `#909399` | Secondary text, hints |

### Component Patterns

- **KB Overview**: `el-row/el-col` grid + `el-card` with folder icon, name, doc count, hover shadow
- **Lists**: `el-table` + `el-pagination` + top search/action bar
- **Detail pages**: `el-tabs` for multi-document switching, `el-tag` for status badges
- **Forms**: `el-dialog` + `el-form` for create/edit, `el-popover` for inline editing
- **Search**: `el-input` with dropdown filter, `el-drawer` for traceability panel
- **Directory**: `el-tree` component
- **Empty state**: `el-empty` when no data
- **Loading**: `v-loading` directive on table/card areas
- **Feedback**: `ElMessage.success/error()` for CUD operations

### Button Conventions

| Action Type | Element Plus Props |
|-------------|-------------------|
| Primary (create/submit/save) | `type="primary"` solid blue |
| Secondary (edit/view/detail) | `type="default"` or `link` text blue |
| Destructive (delete/remove) | `type="danger"` or `link` text red |
| Batch actions (import/export) | `type="default"` with icon |

### Route Structure

```
/                        → redirect /dashboard
/dashboard               → workspace home
/knowledge-bases         → card grid overview
/knowledge-bases/:id     → document list + directory tree
/knowledge-bases/:id/documents/:docId → chunk preview
/faq                     → FAQ knowledge base list
/faq/:id                 → FAQ entries detail
/search                  → unified search
/admin/users             → user management
/admin/api-keys          → API key management
/login                   → login page
```

### Key Implementation Rules

- All components use Composition API with `<script setup lang="ts">`
- API calls go through `src/api/request.ts` Axios instance with JWT interceptor
- Use Pinia for global state (current user, sidebar collapse)
- Match the reference screenshots in `风格参考/` exactly — same layout, spacing, font sizes
- Chinese language interface throughout

## Key References

- **Design spec**: `docs/superpowers/specs/2026-07-28-knowledge-base-design.md` — authoritative
- **Style reference**: `风格参考/` — 5 screenshots of target UI appearance
- **Dify source** (for code reference): `dify/api/core/rag/` — splitter, extractor, embedding, retrieval, rerank patterns
- **Dify models**: `dify/api/models/dataset.py` — data model reference
- **Dify tasks**: `dify/api/tasks/` — Celery task patterns
