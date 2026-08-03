# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

### Local development (recommended)

```bash
# 1. Start Docker infrastructure (run once; lives in separate docker-compose)
docker compose -f ~/Documents/03_Resource/开发环境/docker-compose.yml up -d

# 2. Configure .env at repo root (see README for full env template)

# 3. Install Python deps per service
cd services/kb-common && uv sync
cd services/kb-api && uv sync
cd services/faq-service && uv sync

# 4. Init DB + seed admin user
cd services/kb-common && uv run alembic -c ../../alembic.ini upgrade head
cd services/kb-common && uv run python ../../scripts/seed_admin.py
# → admin / admin123

# 5. Start 3 application processes (separate terminals)
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion --concurrency=2 -l info
cd services/faq-service && uv run uvicorn app.main:app --reload --port 8004

# 6. Start frontend
cd web && pnpm install && pnpm dev   # http://localhost:3000 or :5173
```

### Docker all-in-one mode

```bash
# Prerequisite: infrastructure must be running (step 1 above)
docker compose -f docker-compose.app.yml up -d --build
# Cleanup app containers only (infrastructure stays):
docker compose -f docker-compose.app.yml down
```

> **colima memory**: BGE-M3 requires ≥8GB: `colima stop && colima start --cpu 4 --memory 8`

### Frontend

```bash
cd web
pnpm dev          # dev server with HMR
pnpm build        # type-check + production build
pnpm type-check   # vue-tsc --noEmit
pnpm test:run     # vitest run
```

### Smoke test

```bash
./scripts/smoke_test.sh
# KEEP_SERVICES=1 → keep procs after run
# EXTERNAL_SERVICES=1 → services already running, skip launch
```

## Architecture

**MVP**: 3 application processes + 5 Docker infrastructure containers, sharing one PostgreSQL database.

```
Web (Vue 3) :5173  ──/api/v1──►  kb-api :8000       (FastAPI + BGE-M3)
                      /api/v1/faq ► faq-service :8004  (FastAPI)

kb-worker  (Celery, queue: ingestion)
  └─ MinerU parse → chunk → embed → ES index

Docker infrastructure (dev-services compose, external dev-network):
  PostgreSQL :5432  Redis :6379  Elasticsearch :9200  MinIO :9000  kkFileView :8012
```

### Service Map

| Process | Port | Stack | Responsibilities |
|---------|------|-------|-----------------|
| **kb-api** | 8000 | FastAPI + Celery app | Auth (JWT + API Key), user CRUD, document KB CRUD, directory tree, document upload, search (hybrid kNN+BM25+RRF+rerank), RAG chat, settings, MinerU orchestration |
| **faq-service** | 8004 | FastAPI | FAQ KB CRUD, FAQ directory tree, Q&A pair CRUD, CSV/Excel batch import, FAQ search (exact + semantic fusion) |
| **kb-worker** | — | Celery (kb-api package) | Async ingestion pipeline: PENDING → PARSING (MinerU) → INDEXING (chunk+embed+ES) → COMPLETED |

BGE-M3 + bge-reranker-v2-m3 are loaded **once** in kb-api (~2-3GB RSS). faq-service and kb-worker reuse them via `/internal/embed` on kb-api to avoid duplicating models in memory.

### Shared Package: kb-common

`services/kb-common/` (installed as editable `kb-common` via `uv`):

| Module | Contents |
|--------|----------|
| `kb_common/models.py` | All SQLAlchemy ORM models on shared PG: `User`, `ApiKey`, `KnowledgeBase`, `Directory`, `Document`, `Segment`, `FaqDirectory`, `FaqEntry`, `Setting` |
| `kb_common/database.py` | AsyncSession factory (`SessionLocal`) |
| `kb_common/config.py` | Pydantic Settings from `.env` |
| `kb_common/security.py` | JWT creation/verification, API key hashing, RBAC helpers |
| `kb_common/rag/` | `embedder.py` (BGE-M3), `chunker.py`, `indexer.py`, `searcher.py` (ES hybrid search), `reranker.py` (bge-reranker-v2-m3), `tracer.py` (retrieval trace) |
| `kb_common/clients/` | `minio_client.py`, `es_client.py`, `mineru_client.py`, `llm_client.py` (OpenAI-compatible) |

### Processing Pipeline

```
Upload doc → kb-api (MinIO store + create DB record)
  → kb-api enqueues process_document.delay(doc_id) on Redis
    → kb-worker picks up:
      1. PARSING:  fetch raw from MinIO → MinerU parse → store markdown in MinIO
      2. INDEXING: chunker → embedder → ES index (kb_{kb_id})
         → write Segment rows → mark COMPLETED
```

### Data Model (all in kb_common/models.py, single PG database)

```
users ──► knowledge_bases (kb_type: DOCUMENT|FAQ)
              ├──► directories (tree)
              │       └──► documents ──► segments (chunks, linked to ES)
              └──► faq_directories (tree)
                      └──► faq_entries ──► segments (FAQ chunks, linked to ES)

api_keys ──► users
settings — runtime overrides for .env (LLM key, MinerU key, etc.)
```

ES index naming: `kb_{kb_id}` for document KBs, `faq_{kb_id}` for FAQ KBs.

## Frontend Design System

**Stack**: Vue 3.4+ (`<script setup lang="ts">`), TypeScript strict, Element Plus 2.x, Vite 5.x, Pinia, Vue Router 4, Axios, `@element-plus/icons-vue`.

### Layout Pattern

Left sidebar (dark, 220px) + tab bar + main content (`#f5f7fa`). Navigation: 工作台 / 知识库 / 问答库 / 统一检索 / RAG 问答 / 模型配置 / 用户管理 / API Key 管理.

The tab bar (`stores/tabs.ts` + `components/layout/TabBar.vue`) maintains open pages — tabs auto-add on route navigation, with close/close-others/close-all support. 工作台 is permanent (unclosable).

### Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `--el-color-primary` | `#409EFF` | Primary buttons, links, active states |
| `--el-color-primary-light-9` | `#ecf5ff` | Selected row bg, tag light bg |
| `--el-color-success` | `#67c23a` | Status: COMPLETED |
| `--el-color-warning` | `#e6a23c` | Status: PROCESSING/INDEXING/PARSING |
| `--el-color-danger` | `#f56c6c` | Delete, status: FAILED |
| `--el-color-info` | `#909399` | Secondary text |

### Route Structure

```
/login                    → Login page (public)
/                         → redirect /dashboard
/dashboard                → Workspace home
/knowledge-bases          → Card grid of document KBs
/knowledge-bases/:id      → Directory tree + document table
/knowledge-bases/:id/documents/:docId → Segment preview
/faq                      → FAQ KB list
/faq/:id                  → FAQ entries detail
/search                   → Unified search (with traceability drawer)
/chat                     → RAG Q&A
/settings                 → Model config (LLM/MinerU keys)
/admin/users              → User management (super_admin/admin)
/admin/api-keys           → API Key management (super_admin/admin)
```

### API Layer

All API calls go through `web/src/api/request.ts` — an Axios instance with JWT interceptor. Request interceptor attaches `Authorization: Bearer <token>`. Response interceptor redirects to `/login` on 401.

API modules in `web/src/api/`:
- `auth.ts` — login, /users/me
- `knowledge-base.ts` — KB CRUD
- `document.ts` — doc upload, list, status, segment preview
- `search.ts` — hybrid search
- `chat.ts` — RAG chat
- `faq.ts` — FAQ KB/entry CRUD
- `settings.ts` — runtime settings
- `users.ts` — admin user management

### Key Implementation Rules

- All components use Composition API with `<script setup lang="ts">`
- Pinia stores: `user.ts` (auth state), `app.ts` (sidebar collapse), `tabs.ts` (tab management)
- Chinese language interface throughout
- Match Element Plus conventions: `type="primary"` for create/submit, `type="danger"` for delete, `link` for inline actions
- `v-loading` directive on async areas, `el-empty` for empty states, `ElMessage.success/error()` for CUD feedback

## .env Configuration

See README for the full `.env` template. Key optional vars:
- `LLM_API_KEY` — unset → chat returns friendly "configure LLM" message
- `MINERU_API_KEY` — unset → only txt/md/csv local parse; PDF/DOCX/PPTX/XLSX/HTML need this for MinerU cloud parse
- `LLM_BASE_URL` — OpenAI-compatible endpoint (default: GLM)
- `JWT_SECRET` — dev: `kb-mvp-dev-secret`

Runtime overrides: LLM/MinerU keys can also be set in the UI (平台管理 → 模型配置), stored in `settings` table, taking precedence over `.env`. GET returns `value=""` with `is_set=true` to mask secrets.

## Project Structure

```
knowledge-base/
├── docker-compose.app.yml       # App containers (kb-api/faq-service/kb-worker)
├── alembic.ini                  # DB migrations config (uses kb-common)
├── scripts/
│   ├── smoke_test.sh            # E2E smoke: RAG + FAQ + API Key + settings
│   └── seed_admin.py            # Seed admin user
├── services/
│   ├── kb-common/               # Shared: models, RAG engine, clients, auth, config
│   ├── kb-api/                  # Main API + Celery worker (document KB, search, chat, auth, users, settings)
│   └── faq-service/             # FAQ API (FAQ KB, entries, FAQ search, import)
├── web/                         # Vue 3 + Element Plus frontend
└── docs/                        # Design specs
```
