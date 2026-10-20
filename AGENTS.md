# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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
cd services/kb-common
read -s KGE_BOOTSTRAP_ADMIN_PASSWORD && export KGE_BOOTSTRAP_ADMIN_PASSWORD
uv run python ../../scripts/seed_admin.py
unset KGE_BOOTSTRAP_ADMIN_PASSWORD

# 5. 一键启动（认证策略在启动时确定，二选一）
./scripts/start-dev.sh local      # 本地登录策略：本地账号密码登录（AUTH_PROVIDER=local），权限由系统自己管理
./scripts/start-dev.sh keycloak   # Keycloak 策略：经 SSH 隧道调用 10.10.166.2 身份中心统一登录（服务端默认模式）
./scripts/start-dev.sh status     # 状态；stop / restart 同理（kb-worker 不默认启动，需要时手动起）

# 5b. 手动启动（备选）
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion --concurrency=2 -l info
cd services/faq-service && uv run uvicorn app.main:app --reload --port 8004

# 6. 前端由 start-dev.sh 一并启动（web :8080（永久口径，禁用 3000）/ portal :80）；手动方式：
cd web && pnpm install && pnpm dev   # http://localhost:8080
```

> **认证策略约定**：本地调试不再有免密自动登录通道（DEV_AUTH_TOKEN/dev-login 已移除）。两种策略均由 `scripts/start-dev.sh` 启动时注入：`local` = 本地账号登录（门户用户/角色管理直接管本地 PG 账号）；`keycloak` = 经 `scripts/dev-sso-tunnel.sh` 隧道调用 166.2 身份中心（本地调试也一样，issuer `http://127.0.0.1:8180/realms/jack` 三方一致零改造）。**服务端（10.10.166.2）默认使用 KEYCLOAK 登录**。

### Docker all-in-one mode

```bash
# Prerequisite: infrastructure must be running (step 1 above)
docker compose -f docker-compose.app.yml up -d --build
# Cleanup app containers only (infrastructure stays):
docker compose -f docker-compose.app.yml down
```

> Models are all external HTTP APIs (embedding/rerank/LLM); no local model loading, no extra colima memory needed.

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
# SMOKE_USERNAME / SMOKE_PASSWORD → 已注册的隔离测试账号凭据（必填）
```

## 自动化测试要求（强制）

任何代码任务完成后**必须运行对应层级的自动化测试，全绿才算交付**；测试未跑或未通过，不得宣告任务完成。

| 改动范围 | 必跑命令 | 框架 |
|---------|---------|------|
| 前端（`web/`） | `cd web && pnpm type-check && pnpm test:run` | Vitest（+ @vue/test-utils、msw） |
| 后端（`services/kb-api`） | `cd services/kb-api && uv run pytest tests/ -q` | pytest + pytest-asyncio（`asyncio_mode=auto`） |
| 核心链路 / 发布前 | `./scripts/smoke_test.sh` | E2E 冒烟（需 `SMOKE_USERNAME`/`SMOKE_PASSWORD`） |

- 测试文件位置：前端 `web/src/**/__tests__/*.test.ts`；后端 `services/kb-api/tests/test_*.py`。
- **测试同步维护**：改动函数签名、路由行为或数据流时，必须同步更新受影响测试——禁止只改实现留下挂掉的测试；测试失败时先修复（实现对齐测试或测试对齐新实现），不留「已知失败」。
- 新增功能或修复 bug 时补充对应测试用例，覆盖主路径与边界条件。
- 首轮 vitest 报错可能是瞬时 worker 崩溃，重跑一次确认后再排查。

## Architecture

**MVP**: 3 application processes + 5 Docker infrastructure containers, sharing one PostgreSQL database.

```
Web (Vue 3) :8080  ──/api/v1──►  kb-api :8000       (FastAPI, models external)
                      /api/v1/faq ► faq-service :8004  (FastAPI)

kb-worker  (Celery, queue: ingestion)
  └─ MinerU parse → chunk → embed → ES index

Docker infrastructure (dev-services compose, external dev-network):
  PostgreSQL :5432  Redis :6379  Elasticsearch :9200  MinIO :9000  kkFileView :8012
```

### Service Map

| Process | Port | Stack | Responsibilities |
|---------|------|-------|-----------------|
| **kb-api** | 8000 | FastAPI + Celery app | Auth (JWT + API Key, 账户管理上收门户后仅 local 密码登录 + /users/me), document KB CRUD, directory tree, document upload, search (hybrid kNN+BM25+RRF+rerank), enterprise QA via DeerFlow sidecar (search routes → deerflow_runner → services/deerflow qa_server; sidecar tools call back agent_internal), settings, MinerU orchestration |
| **faq-service** | 8004 | FastAPI | FAQ KB CRUD, FAQ directory tree, Q&A pair CRUD (with per-question similar-question variants), CSV/Excel batch import (same-question rows auto-merged, similar questions in-cell split by `;`/newline), FAQ search (exact on question/similar/keywords + semantic fusion, fail-soft when embedding down) |
| **kb-worker** | — | Celery (kb-api package) | Async ingestion pipeline: PENDING → PARSING (MinerU) → INDEXING (chunk+embed+ES) → COMPLETED |

Embedding & rerank models are **all external** (OpenAI-compatible `/embeddings` + `/rerank` APIs, configured via `EMBEDDING_*` / `RERANK_*`). kb-api does not load any local model; faq-service and kb-worker go through `/internal/embed` on kb-api, which forwards to the external API.

### Shared Package: kb-common

`services/kb-common/` (installed as editable `kb-common` via `uv`):

| Module | Contents |
|--------|----------|
| `kb_common/models.py` | All SQLAlchemy ORM models on shared PG: `User`, `ApiKey`, `KnowledgeBase`, `Directory`, `Document`, `Segment`, `FaqDirectory`, `FaqEntry`, `Setting` |
| `kb_common/database.py` | AsyncSession factory (`SessionLocal`) |
| `kb_common/config.py` | Pydantic Settings from `.env` |
| `kb_common/security.py` | JWT creation/verification, API key hashing, RBAC helpers |
| `kb_common/rag/` | `embedder.py` (external embeddings API), `chunker.py`, `indexer.py`, `searcher.py` (ES hybrid search), `reranker.py` (external rerank API, skipped when unconfigured), `tracer.py` (retrieval trace) |
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
                      └──► faq_entries (similar_questions[]: per-question variants,
                                       one list row each; ES docs per question+variant
                                       share faq_entry_id) ──► segments (FAQ chunks, linked to ES)

api_keys ──► users
settings — runtime overrides for .env (LLM key, MinerU key, etc.)
```

ES index naming: `kb_{kb_id}` for document KBs, `faq_{kb_id}` for FAQ KBs.

## Frontend Design System

**Stack**: Vue 3.4+ (`<script setup lang="ts">`), TypeScript strict, Element Plus 2.x, Vite 5.x, Pinia, Vue Router 4, Axios, `@lucide/vue`(新代码图标), `@element-plus/icons-vue`(存量).

### Layout Pattern

Left sidebar (dark, 220px) + tab bar + main content (`#f5f7fa`). Navigation: 工作台 / 知识库 / 问答库 / 统一检索 / RAG 问答 / 模型配置 / API Key 管理（用户管理已上收统一门户）.

The tab bar (`stores/tabs.ts` + `components/layout/TabBar.vue`) maintains open pages — tabs auto-add on route navigation, with close/close-others/close-all support. 工作台 is permanent (unclosable).

### Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `--el-color-primary` | `#2B6BFF` | Primary buttons, links, active states (品牌蓝,见 frontend-dev-spec §3) |
| `--el-color-primary-light-9` | `#eef3ff` | Selected row bg, tag light bg |
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
/admin/api-keys           → API Key management (super_admin/admin)
```

> 账户与角色管理已上收统一门户（portal/）：门户「系统管理」提供用户管理 + 角色管理（双认证模式可用），后端接口为 `/api/v1/portal/accounts`（local 模式操作本地 PG `users` 表，keycloak 模式经 Keycloak Admin API）与 `/api/v1/portal/roles`。角色含 4 个系统角色 + 自定义角色（`portal_roles` 表），菜单权限可按角色或按用户覆盖（`portal_user_menu_overrides` 表，NULL=全部菜单、列表=白名单）；自定义角色仅控制菜单可见性，应用内写能力仍由系统角色的 `require_role` 决定（自定义角色用户=查看者能力）。系统内不提供用户管理/个人账户页面；`AUTH_PROVIDER=local` 的首个管理员走 `scripts/seed_admin.py`，`AUTH_PROVIDER=keycloak` 下用户由门户统一登录自动建档（自定义角色经 `oidc.role_from_claims(known_codes)` 兼容登录）。

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

### Key Implementation Rules

- 所有数据库 schema 变更必须走 alembic 迁移：新增/修改 `kb_common/models.py` 字段时同步在 `alembic/versions/` 补迁移（先 `alembic heads` 确认无并行冲突），禁止依赖本地 create_all 或手工改表；部署时执行 `alembic upgrade head` 并验证受影响接口
- All components use Composition API with `<script setup lang="ts">`
- Pinia stores: `user.ts` (auth state), `app.ts` (sidebar collapse), `tabs.ts` (tab management)
- Chinese language interface throughout
- Match Element Plus conventions: `type="primary"` for create/submit, `type="danger"` for delete, `link` for inline actions
- `v-loading` directive on async areas, `el-empty` for empty states, `ElMessage.success/error()` for CUD feedback
- 前端统一开发规范（**强制**）：[docs/frontend-dev-spec.md](docs/frontend-dev-spec.md) —— 图标体系（新代码统一 `@lucide/vue` 具名导入、动态图标走 `utils/lucide-icons.ts` 注册表）、蓝色设计 Token（品牌主色 `#2B6BFF`）、TS 风格与工程门禁、AI Coding 约定；与 ui-guidelines.md 冲突时以本文件为准。

### 表格与弹窗布局要求

- UI/UED 设计规范（**强制**）：[docs/ui-guidelines.md](docs/ui-guidelines.md) —— 新增或修改任何界面前必须通读并按其「交付自检清单」核对；核心要求：布局稳定防跳动（切换模式用等宽占位而非移除控件）、说明文案默认 tooltip 不占行、反馈分层（Message/Alert/Tag）、主按钮唯一、状态色语义一致。
- 文档名、标题等主要内容列必须优先分配空间，使用 `min-width` 占据剩余宽度；状态、动作和开关列按实际控件宽度设置固定 `width`，不得让操作列挤占主要内容。
- 长名称使用 `show-overflow-tooltip` 保留完整内容的查看入口；不要通过缩小字号解决列宽问题。
- 单个开关仅展示当前状态文案，避免同时铺开开启和关闭标签；控件与文案应保持同一行，并提供可访问名称。
- 弹窗内表格需核对可用宽度与列宽总和。交付布局调整前检查长中文名称、开关两种状态、空数据及说明文字，避免控件换行、文字挤压和无意义留白。
- 列表「操作」列外显按钮最多 3 个（按使用频率选取），其余收进「更多」下拉，触发器以 `…` 图标表示；危险操作（删除等）归入「更多」并保留二次确认。按钮文案动词开头、明确动作（如「下载原文」而非「原文」）。
- 列表页统一范式（**强制**）：[docs/frontend-dev-spec.md §1.5](docs/frontend-dev-spec.md) —— 四段式结构（过滤栏/工具栏/表格/分页）、表格开启 `border` 支持表头拖拽调整列宽、过滤栏「查询/重置」按钮组 `margin-left: auto` 靠右、分页统一 KgPagination、操作按钮 `link + size="small"`；新增列表页必须照范式实现，参照 KnowledgeCenter.vue 与 DocumentLibraries.vue。
- 统一暗提示组件（**强制**）：[docs/frontend-dev-spec.md §1.6](docs/frontend-dev-spec.md) —— 「? 暗提示」一律使用 `components/common/HelpTip.vue`（行内/角标两种模式），禁止页面自造 ? 角标样式。

## 工程规范索引（强制）

任何任务动手前先读对应规范，交付前过其自检清单：

| 规范 | 文档 | 适用 |
|------|------|------|
| 前端设计及编码规范 | [docs/frontend-dev-spec.md](docs/frontend-dev-spec.md)（+ [docs/ui-guidelines.md](docs/ui-guidelines.md)） | `web/` 一切界面与前端代码 |
| 后端编码规范 | [docs/backend-dev-spec.md](docs/backend-dev-spec.md) | `services/` 一切后端代码 |
| 架构设计规范 | [docs/architecture-spec.md](docs/architecture-spec.md)（现状描述见 [docs/architecture.md](docs/architecture.md)） | 新功能归属、拆分、选型、数据与任务架构决策 |
| 测试规范 | [docs/testing-spec.md](docs/testing-spec.md) | 全部测试编写与交付门禁 |

## .env Configuration

See README for the full `.env` template. Key optional vars:
- `LLM_API_KEY` — unset → chat returns friendly "configure LLM" message
- `MINERU_API_KEY` — unset → only txt/md/csv local parse; PDF/DOCX/PPTX/XLSX/HTML need this for MinerU cloud parse
- `LLM_BASE_URL` — OpenAI-compatible endpoint (default: GLM)
- `JWT_SECRET` — dev: `kb-mvp-dev-secret`

- **Design spec**: `docs/superpowers/specs/2026-07-28-knowledge-governance-expert-design.md` — authoritative
- **Style reference**: `风格参考/` — 5 screenshots of target UI appearance
- **Dify source** (for code reference): `dify/` 源码目录已从 git 移除（本地保留 untracked 参考副本，`api/core/rag/` splitter/retrieval、`api/models/dataset.py`、`api/tasks/` 仍可参考）；外部知识库集成（Dify/RAGFlow）历史代码见 `archive/external-kb-dify-ragflow` 分支
