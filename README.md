# Knowledge Base MVP

RAG 知识库 MVP：文档采集 / 切片 / 向量检索 / LLM 问答 + FAQ 精准匹配，3 进程微服务 + Docker 基础设施。

## 架构

```
                     ┌─────────────────────────────────────────┐
   Web (Vue3)        │  本地原生进程（开发模式，BGE 在 Mac 内存）│
   :3000 (vite)      │                                         │
        │            │  kb-api:8000      FastAPI + BGE-M3      │
        │  /api/v1   │   ├ 文档/目录/检索/问答/认证/设置        │
        │  /api/v1/  │   └ /internal/embed (复用 BGE，无鉴权)  │
        │   faq      │                                         │
        └───────────►│  faq-service:8004 FastAPI (FAQ KB)      │
                     │                                         │
                     │  kb-worker        Celery (ingestion)    │
                     │   ├ MinerU 解析                         │
                     │   └ chunk + embed + ES index            │
                     └────────────┬────────────────────────────┘
                                  │ (dev-network)
            ┌─────────────────────┼─────────────────────┐
            │   Docker 基础设施 (dev-services compose)  │
            │  dev-postgres:5432   dev-redis:6379       │
            │  dev-elasticsearch:9200  dev-minio:9000   │
            │  dev-kkfileview:8012                      │
            └───────────────────────────────────────────┘
```

**3 应用进程**（kb-api / faq-service / kb-worker）+ **5 基础设施容器**（PostgreSQL / Redis / Elasticsearch / MinIO / kkFileView）。

BGE-M3 + bge-reranker-v2-m3 仅在 kb-api 进程加载一次（~2-3GB RSS），faq-service 与 kb-worker 经 `/internal/embed` 复用，避免 Mac 内存爆炸。

## 两种运行模式

### 模式 1（推荐）：本地原生 + Docker 基础设施

应用进程跑在 Mac 原生内存（BGE 模型直接用 Mac RAM），基础设施跑在 Docker。**开发期推荐**，迭代快，无需 colima 加内存。

```bash
# 1. 启动 Docker 基础设施（dev-services compose，一次性）
docker compose -f /path/to/dev-services/docker-compose.yml up -d

# 2. 配置 .env（仓库根目录，参考下方 .env 配置）

# 3. 安装依赖（每个服务首次）
cd services/kb-common && uv sync && cd -
cd services/kb-api && uv sync && cd -
cd services/faq-service && uv sync && cd -

# 4. 初始化数据库表 + 种子 admin
cd services/kb-common && uv run alembic -c ../../alembic.ini upgrade head
cd services/kb-common && uv run python ../../scripts/seed_admin.py
# admin / admin123

# 5. 启动 3 个应用进程（各开一个终端）
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion --concurrency=2 -l info
cd services/faq-service && uv run uvicorn app.main:app --reload --port 8004

# 6. 启动前端
cd web && pnpm install && pnpm dev   # http://localhost:3000
```

登录：`admin` / `admin123` (super_admin)。

### 模式 2：Docker 全量模式（一键）

```bash
docker compose -f docker-compose.app.yml up -d --build
```

> **⚠ colima 内存要求**：BGE-M3 在 kb-api 容器内 CPU 推理，需 colima ≥ 8GB：
> ```bash
> colima stop && colima start --cpu 4 --memory 8
> ```
> 首次启动较慢（BGE 模型下载 ~2GB，容器内首次 embed 约 30-60s）。MVP 不推荐此模式做开发，仅用于验证镜像可部署。

清理：
```bash
docker compose -f docker-compose.app.yml down
```

## .env 配置

仓库根目录 `.env`（开发模式用）：

```env
DATABASE_URL=postgresql+asyncpg://dev:dev123456@127.0.0.1:5432/dev_db
REDIS_URL=redis://:dev123456@127.0.0.1:6379/0
ES_HOST=http://127.0.0.1:9200
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
KKFV_URL=http://127.0.0.1:8012
JWT_SECRET=kb-mvp-dev-secret
# LLM（可选 - 留空则问答返回友好提示）
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=
LLM_MODEL=glm-4-flash
# MinerU（可选 - 云解析暂未实现，MVP 仅本地解析 txt/md/csv；配置 key 不会启用 PDF/DOCX）
MINERU_API_KEY=
```

Docker 全量模式用 `.env.docker`（compose 自动通过 `env_file` 注入，使用 Docker 服务名连基础设施）：

```env
DATABASE_URL=postgresql+asyncpg://dev:dev123456@dev-postgres:5432/dev_db
REDIS_URL=redis://:dev123456@dev-redis:6379/0
ES_HOST=http://dev-elasticsearch:9200
MINIO_ENDPOINT=dev-minio:9000
KKFV_URL=http://dev-kkfileview:8012
KB_API_INTERNAL_URL=http://kb-api:8000
# ...其余同 .env
```

**LLM_API_KEY / MINERU_API_KEY 可选**：
- `LLM_API_KEY` 留空 → 问答接口返回「LLM 调用失败：... 请在 设置 页配置 LLM API Key」，文档检索/溯源照常工作。
- `MINERU_API_KEY` 留空 → txt/md/csv 走本地解析兜底，PDF/DOCX 等格式需配 MinerU 云 API key（可在「平台管理 → 模型设置」页运行时配置，密钥落地 settings 表，GET 接口掩码 `value=""` + `is_set=true`）。

## 冒烟测试

```bash
./scripts/smoke_test.sh
```

脚本自动启动 3 个应用进程（如未运行），覆盖完整链路：
1. 登录 + `/users/me` 字段校验
2. 创建文档知识库
3. 上传文档
4. 等待处理（PENDING → PARSING → INDEXING → COMPLETED）
5. 检索（hybrid: kNN + BM25 + RRF + rerank）
6. 问答（LLM 未配则返回友好提示，非阻断）
7. FAQ KB + 条目 + FAQ 检索（精准 + 语义融合）
8. API Key 创建 + 列表
9. 设置 GET（验证密钥掩码）

预期输出末行：`SMOKE OK`。日志在 `/tmp/kb-smoke/{kb-api,faq-service,kb-worker}.log`。

环境变量：
- `KEEP_SERVICES=1`：脚本结束后保留进程（便于继续调试）
- `EXTERNAL_SERVICES=1`：服务已在外部运行，跳过启动

## 常见问题

| 问题 | 解决 |
|------|------|
| BGE 首次 embed 很慢 | FlagEmbedding 首次下载 ~2GB 模型；后续从 `~/.cache/huggingface` 加载，秒级 |
| Docker 全量模式 OOM | colima ≥ 8GB：`colima stop && colima start --cpu 4 --memory 8` |
| 问答返回 LLM 调用失败 | `.env` 配 `LLM_API_KEY`，或在「平台管理 → 模型设置」页配置 |
| PDF/DOCX 解析失败 | `MINERU_API_KEY` 留空时仅支持 txt/md/csv；其他格式需配 MinerU key |
| `uv sync` 报 `kb-common` 找不到 | 在 `services/kb-common` 先 `uv sync`；Docker 构建已通过 repo-root context 解决 |
| 端口 8000/8004 被占用 | `lsof -i :8000` 找到进程；或改 uvicorn `--port` |
| dev-network 不存在 | 先启 dev-services compose：`docker compose ls` 找配置文件 |

## 项目结构

```
knowledge-base/
├── docker-compose.app.yml       # 应用容器（kb-api/faq-service/kb-worker）
├── .env.docker                  # Docker 全量模式 env
├── scripts/
│   ├── smoke_test.sh            # 端到端冒烟（覆盖 RAG + FAQ + API Key + 设置）
│   └── seed_admin.py            # 种子 admin 用户
├── services/
│   ├── kb-common/               # 共享：models/clients/rag/auth/config
│   ├── kb-api/                  # 文档 KB + 检索 + 问答 + 认证（FastAPI + Celery）
│   └── faq-service/             # FAQ KB + 精准匹配（FastAPI）
└── web/                         # Vue3 + Element Plus 前端
```
