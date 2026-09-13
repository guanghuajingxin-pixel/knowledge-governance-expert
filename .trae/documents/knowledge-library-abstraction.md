# 知识库抽象层：统一「知识库」镜像（RAGFlow + DIFY）检索

## Context

检索工具与提示词中大量写死「Dify 知识库」，导致 RAGFlow 知识库无法被智能体自然使用。用户要求：
1. 新建一层「知识库」抽象：仅从 **RAGFlow / DIFY** 选择登记，**只做镜像**（引用 platform+dataset_id），不支持导入解析新文档。
2. 在「知识应用」下增加「知识库」二级目录（前端页面）。
3. 智能体所有提示词/工具描述抹掉「Dify 知识库」字样，统一说「知识库检索」。
4. 检索策略由抽象层按库类型决定（非提示词实现）。

**用户已确认**：现有「知识源管理」（KnowledgeSource 注册表）是**推送路径**定义，保留不动；新的「知识库」是**检索接口抽象**，独立实体，仅 RAGFlow + DIFY 两类。

**关键现状（已验证，可直接复用）**：
- 检索链路已双通道：`/internal/kb/retrieve`（[agent_internal.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-api/app/routes/agent_internal.py#L50-L135) 按 `dataset_ids`/`ragflow_dataset_ids`/`kb_ids` 分流 Dify/RAGFlow/本地
- 检索策略已内聚于客户端：[dify_client.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-common/kb_common/clients/dify_client.py#L67-L154) 用数据集自身检索配置（含 rerank）；[ragflow_client.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-common/kb_common/clients/ragflow_client.py#L224-L272) 用 RAGFlow 参数——抽象层无需重写
- sidecar `RUNTIME_CTX[thread_id]`（[qa_server.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/deerflow/backend/app/qa_server.py#L777-L785)）注入 `dataset_ids/ragflow_dataset_ids/kb_ids`，工具（[kb_tools.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/deerflow/backend/extensions/kb_tools.py#L46-L131)）读 ctx 调 `/internal/kb/retrieve`——**键已平台无关**，只是 docstring/兜底源写死 Dify
- 引擎拉库接口现成：`GET /dify/datasets`、`GET /ragflow/datasets`（含 document_count），前端封装在 [api/dify.ts](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/web/src/api/dify.ts#L16-L17)、[api/ragflow.ts](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/web/src/api/ragflow.ts#L30-L31)
- 问答页选择器（[chat/index.vue](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/web/src/views/chat/index.vue#L531)）当前用 `listKnowledgeSources`；提交字段 `knowledge_source_ids`，后端 [search.py `_resolve_retrieval_targets`](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-api/app/routes/search.py#L106-L155) 解析为两组 dataset ids

## 实施步骤

### 1. 数据模型 + 迁移（kb-common）
- [models.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-common/kb_common/models.py) 新增 `KnowledgeLibrary`：
  `id, name, platform (String, 'dify'|'ragflow'), dataset_id (String), description (Text, 空), enabled (Bool, default True), created_at, updated_at`；`UniqueConstraint('platform', 'dataset_id')`
- 新迁移 `services/kb-common/alembic/versions/0025_knowledge_libraries.py`（down_revision='0024_sync_source_backend_type'，建表前先跑 `alembic heads` 确认无并行冲突）

### 2. 后端 CRUD（kb-api）
- 新路由文件 `services/kb-api/app/routes/knowledge_library.py`（挂到 main.py）：
  - `GET /api/v1/knowledge-libraries?enabled_only=` 列表
  - `POST /api/v1/knowledge-libraries`（校验 platform ∈ {dify, ragflow}；重复 (platform, dataset_id) 拒绝；name 缺省取引擎库名）
  - `PUT /api/v1/knowledge-libraries/{id}`（启停/改名/描述）
  - `DELETE /api/v1/knowledge-libraries/{id}`
  - 写操作限 `super_admin/admin`，读登录即可
- 引擎库列表**复用现有** `/dify/datasets`、`/ragflow/datasets` 代理接口，不新增

### 3. 检索解析切换到抽象层（kb-api）
- [search.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-api/app/routes/search.py)：
  - `ChatIn` 新增 `library_ids: list[int] | None`（首选）
  - `_resolve_retrieval_targets` 改造：传 `library_ids` → 按 `KnowledgeLibrary` 解析（platform='dify'→dify_ids，'ragflow'→ragflow_ids）；**未传任何目标时，真相源改为 enabled 的 KnowledgeLibrary**；保留 `knowledge_source_ids`/`dify_dataset_ids` 兼容旧链路；非管理员仅可用 enabled 库（越权 403 维持现有口径）
- [agent_internal.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-api/app/routes/agent_internal.py#L51-L88) `/internal/kb/retrieve` 兜底：主兜底 = enabled `KnowledgeLibrary` 按 platform 分组；为空时回退旧 KnowledgeSource 逻辑（过渡保护）

### 4. 工具与提示词「去 Dify 化」（改动为文案，不动逻辑）
- [kb_tools.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/deerflow/backend/extensions/kb_tools.py)：L4 顶部「背后的 Dify 知识库」→「背后的统一知识库层（覆盖企业已接入的各平台知识库）」；L145-146/L185 dingtalk_search 描述与注释「检索 Dify」「Dify 未收录」→「检索知识库」「知识库未收录」；knowledge_search docstring 全文按「知识库检索」口径改写
- [config.py](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/services/kb-api/app/services/agent/config.py)：TOOL_CATALOG `knowledge_search` desc「（Dify 数据集）」→「（统一知识库）」；L48 注释同步
- 全仓库 grep 提示词残留逐处清理（只改用户可见/LLM 可见文案，保留代码键名 DIFY_*）：`services/deerflow/backend`（SOUL/SKILL 默认模板、prompt.py、qa_server 提示片段）、`services/kb-api/app`（错误消息如「Dify 检索失败」→「知识库检索失败」）、`web/src`（问答页选择器分组标题等）
- **不改**：collection.vue / ManualUpload.vue（推送路径页面本身就面向 Dify，属「知识采集」职能）

### 5. 前端
- 新页 `web/src/views/knowledge-libraries/index.vue`（「知识库」镜像管理）：
  - 列表：名称、平台标签（DIFY / RagFlow）、文档数（引擎接口可得）、启用开关（switch 单状态文案）、描述、更新时间；类型筛选；空态引导
  - 「添加知识库」弹窗：平台选择（RAGFlow / DIFY 二选一）→ 拉对应引擎库列表（复用 `listDifyDatasets`/`listRagflowDatasets`）→ 搜索 + 过滤已登记 → 选中回填 name/dataset_id
  - 遵循项目表格规范：名称列 `min-width` 优先、开关单状态、`show-overflow-tooltip`
- 新 API `web/src/api/knowledge-library.ts`（列表/增删改 + 类型）
- [router/index.ts](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/web/src/router/index.ts)：新增路由 `/apply/knowledge-libraries`，`meta: { title: '知识库', icon: 'Collection', group: 'feature', parent: '/apply', menuOrder: 1, roles: ['super_admin','admin','editor'] }`（Sidebar 已支持 parent 嵌套，无需改组件）
- [chat/index.vue](file:///Users/hjx/Documents/01_Project/knowledge-governance-expert/web/src/views/chat/index.vue)：选择器数据源 `listKnowledgeSources` → `listKnowledgeLibraries(enabled_only)`，分组展示「知识库（DIFY/RagFlow）+ 本地文档库」；提交改传 `library_ids`；相关分组文案去 Dify 化

## 验证
1. `alembic heads` 无分叉 → `uv run alembic -c ../../alembic.ini upgrade head`
2. kb-api 单测：`_resolve_retrieval_targets` 新增 library 解析/兜底/403 用例；现有 24 个问答链路测试不回归
3. `pnpm type-check` + `pnpm test:run`
4. 重启：kb-api（--reload 自动）+ sidecar **必须用 `scripts/start-deerflow.sh`**（裸 nohup 会丢 KB_INTERNAL_TOKEN → 全 401）
5. 端到端：知识库页登记 RAGFlow 与 DIFY 各一个库 → 智能问答提问 → sidecar 日志 `internal/kb/retrieve` 全 200 且两平台均有命中 → 引用标签如实显示 RagFlow/DIFY
6. 提示词验收：`GET /api/v1/agent/tools` 返回的描述、 DeerFlow 工具 docstring 中不再出现「Dify」字样（grep 校验）
