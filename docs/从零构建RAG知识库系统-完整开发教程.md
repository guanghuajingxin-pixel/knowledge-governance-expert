# 从零构建 RAG 知识库系统 —— 完整开发教程

本教程按实际开发顺序，逐阶段还原如何从空目录构建一个具备完整功能的 RAG 知识库 MVP。

## 项目概述

**目标**：构建一个文档采集 → 切片 → 向量检索 → LLM 问答的知识库系统，同时支持 FAQ 精准匹配。

**技术栈**：

| 层 | 选型 |
|---|------|
| 后端框架 | FastAPI (Python) |
| 异步任务 | Celery + Redis |
| 向量模型 | BGE-M3 (FlagEmbedding) |
| 重排序 | bge-reranker-v2-m3 |
| 搜索引擎 | Elasticsearch (kNN + BM25 混合检索) |
| LLM | OpenAI 兼容接口（GLM 等） |
| 文档解析 | MinerU（云解析 PDF/DOCX 等） |
| 对象存储 | MinIO |
| 数据库 | PostgreSQL + SQLAlchemy (async) |
| 前端 | Vue 3 + TypeScript + Element Plus + Vite |
| 部署 | Docker Compose |

**架构**：3 个应用进程（kb-api / faq-service / kb-worker）+ 5 个基础设施容器（PostgreSQL / Redis / ES / MinIO / kkFileView），共享一个 PG 数据库。

---

## 第 0 阶段：项目脚手架与基础设施

### 目标
搭建项目骨架：共享包结构、配置管理、依赖管理。

### 关键产出

```
knowledge-base/
├── .env.example              # 环境变量模板
├── .gitignore
├── .python-version            # 3.12
├── docker-compose.app.yml     # 应用容器编排（占位）
└── services/
    └── kb-common/             # 共享 Python 包
        ├── pyproject.toml
        ├── uv.lock
        └── kb_common/
            ├── __init__.py
            ├── config.py          # Pydantic Settings
            ├── clients/__init__.py
            └── rag/__init__.py
```

### 设计决策

**为什么用 `kb-common` 共享包而不是 monolith？**

3 个独立进程（API / Worker / FAQ Service）都需要访问数据库模型、ES 客户端、嵌入模型。共享包避免三处复制粘贴，统一管理依赖版本。

**为什么用 uv 而不是 pip？**

uv 比 pip 快 10-100 倍，且 lock 文件确保三处依赖一致。

**为什么用 Pydantic Settings？**

`kb_common/config.py` 从 `.env` 读取配置，所有服务共用同一份配置源：

```python
# services/kb-common/kb_common/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://..."
    redis_url: str = "redis://..."
    es_host: str = "http://127.0.0.1:9200"
    jwt_secret: str = "kb-mvp-dev-secret"

    class Config:
        env_file = ".env"
```

### 经验教训

- **路径问题**：`env_file` 用相对路径时，从不同目录启动会找不到 `.env`。最终改为根据 `__file__` 计算仓库根绝对路径。
- **config.py 嵌套深度**：`kb_common/config.py` 在 `services/kb-common/kb_common/` 下，`parents[2]` 算到 `kb_common/`，需要 `parents[3]` 才到仓库根，写错了一开始。

---

## 第 1 阶段：数据模型与数据库

### 目标
设计完整的数据库模型、创建迁移、种子初始数据。

### 核心 ORM 模型

```python
# services/kb-common/kb_common/models.py
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # super_admin / admin / user

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    kb_type = Column(String(20), nullable=False)  # DOCUMENT / FAQ
    owner_id = Column(Integer, ForeignKey("users.id"))

class Directory(Base):
    __tablename__ = "directories"
    id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"))
    parent_id = Column(Integer, ForeignKey("directories.id"), nullable=True)

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    dir_id = Column(Integer, ForeignKey("directories.id"))
    status = Column(String(20), default="PENDING")
    # PENDING → PARSING → INDEXING → COMPLETED / FAILED

class Segment(Base):
    __tablename__ = "segments"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer)

class FaqEntry(Base):
    __tablename__ = "faq_entries"
    id = Column(Integer, primary_key=True)
    dir_id = Column(Integer, ForeignKey("faq_directories.id"))
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    key_hash = Column(String(255), nullable=False)
    # 通道控制: search_enabled / chat_enabled
```

### 数据库工具链

```bash
# alembic.ini - 迁移配置
alembic init -t async alembic

# 生成迁移
cd services/kb-common
uv run alembic -c ../../alembic.ini revision --autogenerate -m "init"
uv run alembic -c ../../alembic.ini upgrade head

# 种子管理员
uv run python ../../scripts/seed_admin.py
# → admin / admin123 (super_admin)
```

### 设计决策

**为什么用 asyncpg（异步）而不是 psycopg2（同步）？**

FastAPI 原生支持 async，SQLAlchemy 2.0 的 async session 与 FastAPI 的 `Depends` 完美配合，不会阻塞事件循环。

**为什么所有模型放一起？**

3 个服务共享同一个 PG 数据库，统一模型定义避免跨服务的不一致。`kb-common` 作为唯一真相源。

### 经验教训

- **elationship 导入**：初始版本 import 了未使用的 relationship，SQLAlchemy 不会报错但 IDE 会警告，后续清理了。

---

## 第 2 阶段：前端骨架

### 目标
搭建 Vue 3 前端骨架：路由、状态管理、HTTP 客户端、布局框架。

### 技术选型

```
web/
├── package.json          # Vue 3.4, Element Plus 2.x, Vite 5
├── vite.config.ts
├── tsconfig.json
└── src/
    ├── main.ts           # 入口：挂载 app + pinia + router
    ├── App.vue
    ├── router/index.ts   # Vue Router 4
    ├── stores/
    │   ├── user.ts       # 认证状态
    │   └── app.ts        # 全局 UI 状态
    ├── api/
    │   └── request.ts    # Axios 实例 + JWT 拦截器
    ├── styles/
    │   ├── global.scss
    │   └── variables.scss
    ├── types/            # TypeScript 类型定义
    └── views/            # 页面组件
```

### Axios 拦截器模式

```typescript
// web/src/api/request.ts
const request = axios.create({ baseURL: '/api/v1' })

request.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  res => res,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      router.push('/login')
    }
    return Promise.reject(error)
  }
)
```

### 布局设计

左暗色侧边栏（220px）+ 右主内容区（#f5f7fa）：

```
┌──────────┬──────────────────────────────────────┐
│  Logo    │  顶栏（面包屑）                       │
│          ├──────────────────────────────────────┤
│  工作台  │                                      │
│  知识库  │        <router-view />               │
│  问答库  │                                      │
│  统一检索│                                      │
│  RAG问答 │                                      │
│  模型配置│                                      │
│  用户管理│                                      │
│  API Key │                                      │
└──────────┴──────────────────────────────────────┘
```

### 设计决策

**为什么选 Element Plus？**

Vue 3 生态中最成熟的组件库，中文文档完善，表单/表格/对话框等开箱即用。

**为什么用 Pinia 而不是 Vuex？**

Pinia 是 Vue 3 官方推荐的状态管理，TypeScript 支持更好，API 更简洁。

**开发阶段为什么不用 MSW（Mock Service Worker）？**

初始阶段用 MSW mock 了所有 API，让前端可以独立开发。后续逐步替换为真实后端。

---

## 第 3 阶段：认证系统

### 目标
实现完整的登录/认证/权限系统（前后端）。

### 后端实现

```python
# JWT 令牌
# services/kb-common/kb_common/security.py
def create_access_token(user_id: int, role: str) -> str:
    return jwt.encode({
        "sub": str(user_id), "role": role,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }, settings.jwt_secret)

def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    payload = jwt.decode(token, settings.jwt_secret, ...)
    user = await db.get(User, int(payload["sub"]))
    return user

# RBAC 依赖注入
def require_role(*roles: str):
    async def checker(current_user = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(403)
        return current_user
    return checker

# services/kb-api/app/routes/auth.py
@router.post("/login")
async def login(form: OAuth2PasswordRequestForm):
    user = await authenticate(form.username, form.password)
    token = create_access_token(user.id, user.role)
    return {"access_token": token, "token_type": "bearer"}
```

### 前端登录页

```vue
<!-- web/src/views/login/index.vue -->
<template>
  <div class="login-container">
    <el-form @submit.prevent="handleLogin">
      <el-input v-model="username" />
      <el-input v-model="password" type="password" />
      <el-button type="primary" native-type="submit">登录</el-button>
    </el-form>
  </div>
</template>

<script setup lang="ts">
const userStore = useUserStore()
const router = useRouter()

async function handleLogin() {
  await userStore.login(username.value, password.value)
  router.push('/')
}
</script>
```

### 设计决策

**为什么用 JWT 而不是 Session？**

微服务架构中 Session 需要共享存储，JWT 无状态，faq-service 可直接验证而不必回调 kb-api。

**RBAC 粒度**：三级角色 — `super_admin`（全部权限）、`admin`（管理权限）、`user`（基本权限）。

---

## 第 4 阶段：基础设施客户端

### 目标
封装所有外部服务的客户端（ES、MinIO、MinerU、LLM、向量模型）。

### 客户端清单

```python
# services/kb-common/kb_common/clients/

# es_client.py - Elasticsearch
es = AsyncElasticsearch(settings.es_host)

# minio_client.py - MinIO 对象存储
minio = Minio(settings.minio_endpoint, ...)
# 两个 bucket: kb-documents (原始文件), kb-parsed (解析结果)

# mineru_client.py - MinerU 文档解析
async def parse_document(file_bytes: bytes, filename: str) -> str:
    # 调用 MinerU API，返回 markdown

# llm_client.py - LLM 对话
async def chat(messages: list[dict], ...) -> str:
    # OpenAI 兼容接口

# services/kb-common/kb_common/rag/embedder.py - 向量化
class Embedder:
    def __init__(self):
        self.model = FlagModel("BAAI/bge-m3", ...)
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
```

### 设计决策

**为什么用 MinIO 而不是本地文件系统？**

Docker 部署时文件系统不持久化。MinIO 兼容 S3 API，本地开发和云部署同一套代码。

**为什么用 BGE-M3？**

支持中英双语，支持稠密向量（dense）和稀疏向量（sparse/BM25）双表征，1024 维向量在精度和效率间平衡。

---

## 第 5 阶段：知识库 CRUD + 文档管理

### 目标
后端实现知识库、目录、文档的完整 CRUD，前端实现目录树 + 文档表格。

### 后端路由

```python
# services/kb-api/app/routes/knowledge_base.py
@router.post("/")          # 创建 KB
@router.get("/")           # 列表（分页）
@router.get("/{id}")       # 详情
@router.put("/{id}")       # 更新
@router.delete("/{id}")    # 删除

# services/kb-api/app/routes/document.py
@router.post("/upload")    # 上传文档 → MinIO → 入队 Celery
@router.get("/")           # 文档列表（分页 + 状态筛选）
@router.get("/{id}")       # 文档详情
@router.delete("/{id}")    # 删除文档
@router.get("/{id}/segments")  # 切片预览
```

### 前端关键页面

**知识库卡片网格** (`/knowledge-bases`)：
- 响应式卡片网格展示所有 KB
- 创建对话框（名称 + 描述 → POST API）
- 点击卡片进入详情

**知识库详情** (`/knowledge-bases/:id`)：
- 左侧：`el-tree` 目录树（懒加载子节点）
- 右侧：`el-table` 文档列表（分页 + 状态标签）+ 上传按钮
- 目录新增/重命名/删除
- 文档上传（`el-upload` → POST `/upload`）

**文档切片预览** (`/knowledge-bases/:id/documents/:docId`)：
- 展示文档的所有分段，每段显示内容和 chunk index

### 设计决策

**为什么目录树用懒加载？**

大型知识库可能有数百个目录，一次性加载全部性能差。懒加载按需获取子节点。

---

## 第 6 阶段：RAG 检索引擎

### 目标
实现完整的 RAG pipeline：切片 → 向量化 → ES 索引 → 混合检索 → 重排序。

### 核心组件

```python
# services/kb-common/kb_common/rag/

# chunker.py - 文本切片
class Chunker:
    def chunk(self, text: str) -> list[str]:
        # 按段落 + 滑动窗口切片（chunk_size=512, overlap=50）

# embedder.py - 向量化
class Embedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        # BGE-M3 dense + sparse 双表征

# indexer.py - ES 索引
class Indexer:
    async def index(self, kb_id: int, segments: list[Segment]) -> None:
        # 写入 ES 索引 kb_{kb_id}
        # mapping: dense (1024-d kNN) + sparse (BM25) + text + metadata

# searcher.py - 混合检索
class Searcher:
    async def search(self, kb_id: int, query: str, top_k: int = 10):
        # 1. kNN 检索（dense vector 余弦相似度）
        # 2. BM25 检索（sparse vector）
        # 3. RRF 融合排序
        # 4. bge-reranker-v2-m3 重排序
        return hits

# reranker.py - 重排序
class Reranker:
    def rerank(self, query: str, docs: list[str]) -> list[float]:
        # Cross-encoder 评分
```

### ES 索引设计

```json
{
  "mappings": {
    "properties": {
      "content": {"type": "text", "analyzer": "standard"},
      "dense_vector": {"type": "dense_vector", "dims": 1024, "index": true, "similarity": "cosine"},
      "sparse_vector": {"type": "rank_features"},
      "doc_id": {"type": "integer"},
      "kb_id": {"type": "integer"},
      "chunk_index": {"type": "integer"}
    }
  }
}
```

### 检索流程

```
用户查询 "什么是 RAG"
  │
  ├─ 1. Embedder.embed(query) → dense + sparse vector
  ├─ 2. ES 混合检索
  │    ├─ kNN (dense): cosine similarity → top 50
  │    └─ BM25 (sparse): term match   → top 50
  ├─ 3. RRF 融合: 取 top 20
  ├─ 4. Reranker 重排序: 取 top 10
  └─ 5. 返回 hits (content + score + doc metadata)
```

### 设计决策

**为什么用混合检索而不是纯 kNN？**

纯向量检索对关键词匹配弱（如 "API Key" 精确查询），BM25 擅长精确匹配，RRF 结合两者优势。

**为什么需要 Reranker？**

BGE-M3 是双塔模型（bi-encoder），query 和 doc 独立编码 → 速度快但精度有限。bge-reranker-v2-m3 是交叉编码器（cross-encoder），query+doc 联合编码 → 更精确但速度慢。先粗筛再精排是最佳实践。

---

## 第 7 阶段：LLM RAG 问答

### 目标
基于检索结果调用 LLM 生成答案，并返回引用溯源。

### 实现

```python
@router.post("/chat")
async def chat(request: ChatRequest):
    # 1. 检索相关片段
    hits = await searcher.search(kb_id, request.question, top_k=5)

    # 2. 构建 prompt
    context = "\n\n".join(h["content"] for h in hits)
    prompt = f"""基于以下参考资料回答问题。如果资料不足以回答，请如实说明。

参考资料：
{context}

问题：{request.question}
"""

    # 3. 调用 LLM
    answer = await llm_client.chat([
        {"role": "user", "content": prompt}
    ])

    # 4. 返回答案 + 引用
    return {
        "answer": answer,
        "references": [{
            "content": h["content"],
            "document_name": h["doc_name"],
            "score": h["score"]
        } for h in hits]
    }
```

### 前端 RAG 问答页

```
┌──────────────────────────────────────────────────────┐
│  选择知识库：[下拉选择]                                │
│                                                      │
│  ┌──────────────────────────────────────────────────┐ │
│  │  用户：什么是 RAG？                               │ │
│  │  AI：RAG（检索增强生成）是...                      │ │
│  │      📎 引用 (3)                                  │ │
│  │      1. RAG 综述.pdf · score: 0.95               │ │
│  │      2. LLM 应用指南.md · score: 0.87            │ │
│  └──────────────────────────────────────────────────┘ │
│                                                      │
│  [输入框________________________] [发送]              │
└──────────────────────────────────────────────────────┘
```

### 设计决策

**LLM 未配置时怎么办？**

不阻塞其他功能。检索/溯源照常工作，LLM 调用返回友好提示：「请在设置页配置 LLM API Key」。

**LLM Key 存储在哪？**

优先级：`settings` 表（通过 UI 配置） > `.env` 文件。GET 接口返回 `value=""` + `is_set=true` 掩码保护。

---

## 第 8 阶段：Celery 异步采集流水线

### 目标
文档上传后异步处理：解析 → 切片 → 向量化 → ES 索引，不阻塞 API 响应。

### 流水线

```
上传文档 → MinIO 存储 + DB 记录 (status=PENDING)
         → Celery task: process_document.delay(doc_id)
              │
              ├─ PARSING (status=PARSING)
              │   → 从 MinIO 取原始文件
              │   → MinerU 解析 → markdown
              │   → 写入 MinIO (kb-parsed bucket)
              │
              ├─ INDEXING (status=INDEXING)
              │   → chunker.chunk(markdown) → 切片列表
              │   → embedder.embed(chunks)  → 向量
              │   → indexer.index(kb_id, segments) → ES
              │   → 写入 Segment 行 (PG)
              │
              └─ COMPLETED (status=COMPLETED)
```

### Celery 配置

```python
# services/kb-api/app/worker.py
from celery import Celery

celery_app = Celery("kb_worker")
celery_app.config_from_object({
    "broker_url": settings.redis_url,
    "task_routes": {"process_document": {"queue": "ingestion"}},
})

@celery_app.task(name="process_document")
def process_document(doc_id: int):
    # 协调全流程
    ...
```

### 设计决策

**为什么选择 Celery + Redis 而不是 ARQ 或直接 asyncio？**

Celery 生态成熟，支持重试、超时、监控（Flower），Redis 已在基础设施中可复用。ARQ 更轻量但社区资源少。

**为什么 Worker 用同步 task 而不是 async？**

Celery task 默认同步，内部通过 `asyncio.run()` 调用异步客户端。同步 task 更简单且 Celery 对同步 task 的监控更完善。

**并发控制**：`--concurrency=2`，因为 BGE 模型推理是 CPU-bound（在 Mac 上没有 GPU），2 并发已耗尽资源。

---

## 第 9 阶段：FAQ 独立服务

### 目标
独立 FAQ 微服务：FAQ KB CRUD、目录树、Q&A 条目批量导入、FAQ 检索。

### 架构

```
Web :3000  ──/api/v1/faq──►  faq-service :8004
                               ├── KB CRUD (faq_knowledge_bases)
                               ├── 目录树 (faq_directories)
                               ├── 条目 CRUD (faq_entries)
                               ├── CSV/Excel 批量导入
                               └── FAQ 检索（精准 + 语义融合）
                                    │
                                    └── /internal/embed@kb-api:8000 (复用 BGE)
```

### 为什么 FAQ 独立成服务？

FAQ 和文档知识库的数据模型、检索逻辑、业务规则都不同：
- 文档 KB：长文本切片 + LLM 问答
- FAQ：短 Q&A 对 + 精准匹配优先

独立服务便于独立扩缩容，且 `/api/v1/faq` 路径前缀天然适合反向代理分发。

### BGE 复用

FAQ 服务和 Worker 不做自己的模型加载（~2-3GB RSS），而是通过 kb-api 的内部接口复用：

```python
# faq-service 调用 kb-api
POST http://kb-api:8000/internal/embed
{"texts": ["什么是 RAG？"]}
→ {"embeddings": [[0.1, 0.2, ...]]}
```

这样 Mac 内存中只加载一份 BGE 模型。

### FAQ 检索策略

与文档检索的双路融合不同，FAQ 检索强调精准匹配：

```python
# 1. 精准匹配：问题与 FAQ 条目的 question 字段做语义相似度
# 2. 语义检索：ES kNN 检索，补充精准匹配遗漏的相关条目
# 3. 融合排序：精准匹配结果优先，语义结果补充
```

### 前端 FAQ 页面

- **列表页**：卡片网格展示 FAQ 知识库
- **详情页**：目录树 + Q&A 条目表格 + 搜索 + 批量导入按钮
- **批量导入**：上传 CSV/Excel → 解析 → 批量创建 entry

---

## 第 10 阶段：统一检索 + 用户管理 + API Key 管理

### 统一检索页

```
┌──────────────────────────────────────────────────────┐
│  [选择知识库 ▼]  [输入检索词______________] [搜索]    │
│                                                      │
│  ┌──────────────────────┬───────────────────────────┐│
│  │  检索结果列表         │  溯源抽屉（点击某条展开）  ││
│  │  ┌──────────────────┐│  ┌───────────────────────┐││
│  │  │ 1. 匹配片段...    ││  │  文档：RAG 综述.pdf    │││
│  │  │    score: 0.95    ││  │  片段：...完整内容...  │││
│  │  │    [查看溯源]     ││  │  相似度：0.95          │││
│  │  └──────────────────┘│  └───────────────────────┘││
│  │  ┌──────────────────┐│                           ││
│  │  │ 2. ...            ││                           ││
│  │  └──────────────────┘│                           ││
│  └──────────────────────┴───────────────────────────┘│
└──────────────────────────────────────────────────────┘
```

### 用户管理（管理员）

- 用户 CRUD 表格（分页、搜索、角色筛选）
- 新增/编辑用户对话框
- 角色：super_admin / admin / user
- RBAC 保护：仅 super_admin 和 admin 可访问

### API Key 管理

- API Key 创建/列表/删除
- 通道控制：可选择启用检索通道和/或问答通道
- Key 仅创建时显示一次完整值（安全设计）
- 存储 SHA256 哈希

### API Key 双通道鉴权

```python
# 外部 API 调用可以通过 API Key 鉴权（不需要 JWT）
# 检索通道：可用于 ES 检索
# 问答通道：可用于 LLM 问答
# 两个通道独立控制，满足不同场景的安全隔离需求
```

---

## 第 11 阶段：测试、部署、文档

### 冒烟测试

```bash
#!/bin/bash
# scripts/smoke_test.sh
# 端到端覆盖：
# 1. 登录 + 用户信息校验
# 2. 创建知识库 → 上传文档 → 等待处理完成
# 3. 检索 + 问答验证
# 4. FAQ KB + 条目 + FAQ 检索
# 5. API Key 创建 + 列表
# 6. 设置接口验证（密钥掩码）
```

### Docker 部署

```yaml
# docker-compose.app.yml
services:
  kb-api:
    build: ./services/kb-api
    ports: ["8000:8000"]
    env_file: .env.docker

  faq-service:
    build: ./services/faq-service
    ports: ["8004:8004"]
    env_file: .env.docker

  kb-worker:
    build: ./services/kb-api
    command: celery -A app.worker worker -Q ingestion -l info
    env_file: .env.docker
```

### Dockerfile 注意点

**构建上下文**：Dockerfile 在 `services/kb-api/`，但需要访问 `services/kb-common/` 目录，所以构建上下文要设为仓库根：

```yaml
build:
  context: .            # 仓库根
  dockerfile: services/kb-api/Dockerfile
```

---

## 第 12 阶段：迭代完善

### MinerU 云解析

接入 MinerU 云服务解析二进制文档（PDF/DOCX/PPTX/XLSX/HTML）：

```python
# 未配置 MINERU_API_KEY → 仅本地解析 txt/md/csv
# 已配置 → 二进制格式走 MinerU 云解析
```

### 用户管理全 CRUD

前后端完整的用户管理 → 详见第 10 阶段。

### KB 收藏 + 状态字段

`KbFavorite` 模型 + `KnowledgeBase.status` 字段，支持收藏知识库和管理状态。

### 知识中心

统一知识管理视图，融合文档 KB 和 FAQ KB 的管理入口：

```
知识中心
├── 知识管理 Tab
│   ├── 目录树（文档 KB + FAQ KB 统一树）
│   └── 详情弹窗
├── 任务队列 → 查看 Celery 采集进度
└── 回收站 → 软删除文档恢复
```

### Tab 标签页导航

`TabBar` 组件自动维护打开过的页面标签，支持关闭/关闭其他/关闭全部。工作台页签不可关闭。路由跳转自动添加标签。

体验细节：
- `stores/tabs.ts` 维护标签列表，与 `router` 联动
- 左侧侧边栏点击 → 自动添加/激活对应标签
- 标签关闭时自动切换到相邻标签

### 文档软删除

`documents` 表添加 `deleted_at` 字段，删除操作改为软删除。回收站可恢复。

---

## 经验总结

### 架构经验

1. **共享包模式**：`kb-common` 作为唯一真相源，避免 3 个服务间的代码重复和版本漂移。
2. **BGE 模型复用**：Mac 内存有限，模型只加载一次，通过内部 HTTP 接口共享。
3. **异步流水线**：上传是同步接口（秒级返回），处理是异步 Celery（分钟级），用户体验好。
4. **配置文件优先级**：settings 表 > .env > 默认值，满足运行时动态配置需求。

### 前端经验

1. **API 层抽象**：所有 API 调用通过 `web/src/api/` 模块，不直接在组件中调 axios。
2. **TypeScript 类型**：接口返回值全部有类型定义，`types/` 目录保持与后端 schema 对齐。
3. **Element Plus 惯例**：`type="primary"` 创建、`type="danger"` 删除、`link` 行内操作。
4. **状态驱动 UI**：`v-loading` 加载态、`el-empty` 空态、`ElMessage` 操作反馈。

### 开发流程

1. **先设计数据模型**：数据库结构是基础，后续所有功能都围绕它。
2. **前端先用 Mock**：后端没完成时前端可用 MSW mock 独立开发。
3. **契约对齐**：前后端字段不一致是最常见的 bug 来源，冒烟测试能有效发现。
4. **冒烟测试投入产出比高**：30 条用例覆盖核心链路，几分钟跑完。

### 避坑指南

| 坑 | 原因 | 解决 |
|----|------|------|
| Worker 连不上 kb-api | 容器内用 `kb-api` 服务名，宿主机用 `localhost` | `.env.docker` 单独配置 `KB_API_INTERNAL_URL` |
| BGE 首次 embed 超慢 | 首次需下载 ~2GB 模型 | 预热一次，后续从 `~/.cache/huggingface` 秒加载 |
| `uv sync` 找不到 `kb-common` | 共享包未先安装 | 先在 `services/kb-common` 执行 `uv sync` |
| Colima OOM | BGE-M3 需要 2-3GB | `colima start --memory 8` |
| asyncpg 连接池耗尽 | 默认 pool_size=10 | 3 服务共享，调整为合适大小 |

---

## 附录：完整项目结构

```
knowledge-base/
├── .env                          # 本地开发环境变量
├── .env.docker                   # Docker 部署环境变量
├── alembic.ini                   # 数据库迁移配置
├── docker-compose.app.yml        # 应用容器编排
├── scripts/
│   ├── seed_admin.py
│   └── smoke_test.sh
├── services/
│   ├── kb-common/                # 共享 Python 包
│   │   ├── pyproject.toml
│   │   └── kb_common/
│   │       ├── config.py         # Pydantic Settings
│   │       ├── database.py       # AsyncSession 工厂
│   │       ├── models.py         # 全部 ORM 模型
│   │       ├── security.py       # JWT + RBAC
│   │       ├── clients/          # ES / MinIO / MinerU / LLM
│   │       └── rag/              # chunker / embedder / indexer / searcher / reranker / tracer
│   ├── kb-api/                   # 文档 KB API + Celery Worker
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI 应用
│   │   │   ├── worker.py         # Celery 应用
│   │   │   ├── schemas.py        # Pydantic 请求/响应模型
│   │   │   └── routes/           # auth / knowledge_base / document / search / chat / settings / users / api_keys / knowledge_center
│   │   └── Dockerfile
│   └── faq-service/              # FAQ API
│       ├── app/
│       │   ├── main.py
│       │   └── routes/           # faq KB / directory / entry / search / import
│       └── Dockerfile
├── web/                          # Vue 3 前端
│   ├── src/
│   │   ├── api/                  # Axios 模块（auth / knowledge-base / document / search / chat / faq / settings / users / knowledge-center）
│   │   ├── components/layout/    # Sidebar / TabBar
│   │   ├── layouts/              # AppLayout
│   │   ├── router/               # 路由配置
│   │   ├── stores/               # Pinia（user / app / tabs）
│   │   ├── styles/               # 全局样式 + 变量
│   │   ├── types/                # TypeScript 类型
│   │   └── views/                # 页面组件
│   └── Dockerfile
└── docs/
```

---

> **本教程基于实际 git 历史还原（commit `b1858be` → `150444f`），共计 36 个 commit，覆盖从空目录到功能完整的 MVP 全过程。**
