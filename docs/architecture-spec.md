# 架构设计规范(architecture-spec)

> 本文是**架构决策与设计约束**——新功能\"放在哪、怎么拆、按什么规则选型\"必须先过本文;系统现状全景见 `docs/architecture.md`(权威描述,基于代码实现)。
> 前端设计约束见 `docs/frontend-dev-spec.md` + `docs/ui-guidelines.md`;后端编码细则见 `docs/backend-dev-spec.md`。

## 1. 总体形态与不可违背约束

- 形态:微服务化 Python 后端(FastAPI)+ Vue 3 前端 + Docker 基础设施 + **全外接模型 API**。
- **模型零本地加载**:embedding / rerank / LLM 一律外部 OpenAI 兼容 HTTP API。禁止引入本地模型推理依赖(不新增显存/内存负担,这是既定架构决策)。
- **单一 PostgreSQL 共享库**:所有服务的业务表同库;服务间不直连对方专属存储,跨服务数据需要时走 API 或同库直读(需评审)。
- **前端只经网关访问后端**:Web → `/api/v1`(kb-api)、`/api/v1/faq`(faq-service);服务间内部调用走内网 + 服务密钥。

## 2. 服务边界与职责判定

新增功能先按下表判定归属,拿不准时以\"数据归属 + 事务边界\"为准:

| 服务 | 职责 | 判定规则 |
|---|---|---|
| **kb-api** :8000 | 认证、知识库/文档/目录 CRUD、检索编排、设置、Wiki 生成、治理 | 默认归属;凡涉及共享 PG 业务表的首选这里 |
| **faq-service** :8004 | FAQ 库/词条/检索 | 仅 FAQ 专属域;embedding 经 kb-api `/internal/embed` 转发,不直连模型 |
| **kb-worker**(Celery) | 长耗时摄取管道:解析→切片→向量化→索引 | CPU/IO 密集、分钟级、无需与用户交互的任务 |
| **deerflow sidecar** :2027 | 企业级问答编排(Lead Agent + Sub-Agent) | 仅问答链路;工具回调 kb-api 内部接口 |
| **kb-common** | ORM 模型、DB 会话、配置、安全、RAG 组件、外部客户端 | 被 ≥2 个服务使用的代码才下沉;单一服务的业务逻辑不入 common |

拆分红线:路由层不写业务逻辑(下放 services);services 不感知 HTTP(不 import fastapi);kb-common 不依赖任何 app 层。

## 3. 数据架构

- 命名:表复数蛇形(`library_documents`);UUID 主键;`created_at/updated_at` 必备;枚举用 String + 代码内常量集(不依赖 PG enum 类型)。
- 删除策略:父子关系显式 `ondelete`(级联清理子分段/任务);软删(回收站)仅对用户可见资产,保留期后异步清理。
- **schema 演进唯一通道是 alembic**;迁移文件线性追加,禁止修改已合并迁移。
- 跨模块聚合视图(如知识中心跨库聚合)只读不落表,查询时 JOIN;固化字段(如钉钉 source_url)入库前先加迁移补列,读路径带映射反查兜底。

## 4. 异步任务架构

按耗时与可靠性分级选型:

| 场景 | 方案 | 示例 |
|---|---|---|
| 秒级、进程内 | asyncio 后台任务(`_spawn` 模式 + 库级锁) | Wiki 生成、轻量刷新 |
| 分钟级、需重试/横向扩展 | Celery(队列 `ingestion`) | 文档摄取管道 |
| 定时 | XXL-Job 调度器触发批处理 | 钉钉同步、解析刷新 |
| 用户触发长操作 | 前端分批循环调批接口(每批 ≤500 条) | 删除全部(数量可见递减) |

任务状态机统一:PENDING → RUNNING → COMPLETED / FAILED,失败必须落中文原因;服务重启恢复遗留 RUNNING 为可重试的 FAILED。

## 5. 外部依赖治理

- 所有外部 HTTP(模型/钉钉/MinerU 云)统一经 `kb_common/clients/` 封装,超时显式声明(LLM 120s、预演类 10min),重试 ≤1 次。
- **fail-soft 优先**:外部依赖不可用降级不熔断主流程(如 FAQ 语义检索在 embedding 不可用时回退精确匹配;LLM 未配置返回友好提示)。
- 运行时可覆盖配置经 `settings` 表(模型配置页),env 为兜底;两者合并逻辑收敛在 `llm_resolver` 一处。

## 6. 基础设施与部署

- 开发态基础设施独立 compose(dev-network 共享),应用容器 `docker-compose.app.yml` 只含应用进程。
- 端口分配:8000 kb-api / 8004 faq / 8012 kkFileView / 2027 deerflow / 2028 mineru;新服务申请新端口不复用。
- 数据卷:MinIO 数据与 PG 数据持久化在宿主卷;容器重建不丢业务数据。

## 7. 架构决策记录(ADR)

重大决策(引入新服务/新中间件/改动数据归属/换技术栈)必须补一条简式 ADR 到本节,格式:`日期 / 决策 / 理由 / 影响`,三行以内:

| 日期 | 决策 | 理由 | 影响 |
|---|---|---|---|
| 2026-09 | 账户体系上收统一门户,系统内仅保留 local 登录 | 企业统一身份治理 | 用户管理页移除,角色双轨制 |
| 2026-10 | 破坏性批量操作前端分批化 | 大批量一次删除超时且无进度感 | 批量接口增加 limit 参数 |

## 8. 自检清单(架构)

- [ ] 新功能归属服务判定经过 §2 表格;无反向依赖
- [ ] 未引入本地模型加载;外部调用有超时与 fail-soft
- [ ] schema 变更走 alembic;数据归属单一服务
- [ ] 长任务按 §4 分级选型;失败可观测(状态+中文原因)
- [ ] 重大决策已补 ADR
