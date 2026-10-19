# 后端开发规范(backend-dev-spec)

> 适用范围:`services/kb-api`(主服务)、`services/kb-common`(共享包)、`services/faq-service`、`services/deerflow`(问答 sidecar)。
> 本文是**编码与工程约定**的事实源;系统现状描述见 `docs/architecture.md`,架构决策约束见 `docs/architecture-spec.md`,测试细则见 `docs/testing-spec.md`。与 AGENTS.md 冲突时以本文为准并同步更新 AGENTS.md 指针。

## 1. 技术栈与项目结构

| 项 | 约定 |
|---|---|
| 语言/版本 | Python 3.11+,全程类型注解 |
| Web 框架 | FastAPI(async 路由),Pydantic v2 入参校验 |
| ORM | SQLAlchemy 2.0 async(`AsyncSession` + asyncpg) |
| 包管理 | `uv`(`uv sync` / `uv run`),锁文件 `uv.lock` 随代码提交 |
| 共享包 | `kb-common` 以 editable 方式安装,模型/客户端/工具层唯一 |
| 后台任务 | Celery(队列 `ingestion`)+ 进程内 asyncio 后台任务(见 §6) |

分层调用方向(禁止反向依赖):`routes → services → kb_common(models / clients / rag)`。

```
services/kb-api/app/
├── routes/       # 路由层:参数校验、鉴权、调 services、序列化输出;不放业务逻辑
├── services/     # 业务层:跨表事务、编排、后台任务;路由与任务共用
├── deps.py       # get_current_user / require_role 依赖注入
└── schemas.py    # 与 db 模型分离的响应模型(存量逐步收敛,新代码可路由内定义 _out)
```

## 2. 路由规范

- 每个 APIRouter 统一前缀 `/api/v1/<模块>`,`tags=[\"<模块>\"]`;路由文件按模块命名(如 `knowledge_center.py`)。
- **鉴权**:登录用户 `u=Depends(get_current_user)`;写操作加角色 `dependencies=[Depends(require_role(\"super_admin\", \"admin\"[, \"editor\"]))]`。新接口必须显式声明其一,不允许裸奔。
- **入参**:Query 参数写清 `description`;Body 用 Pydantic 模型 + `Field` 限定长度/上限(如批量 ID ≤100),非法输入 422 由框架统一抛出。
- **出参**:统一模块内 `_xxx_out()` 函数把 ORM 对象转 dict(时间经 `_to_utc_iso` 转带时区 UTC);错误原因字段(如 `error`/`message`)必须可读中文,给前端直接展示。
- **HTTP 语义**:404 不存在;409 状态冲突(如\"解析中不可删除\");422 参数/前置校验不过;500 仅兜底。`detail` 写用户能懂并知道下一步做什么的中文。

## 3. 数据库规范

- **一切 schema 变更走 alembic 迁移**:改 `kb_common/models.py` 必须同步 `alembic/versions/`(先 `alembic heads` 确认无并行头);禁止 `create_all`、禁止手工改表;部署执行 `alembic upgrade head`。
- 表约定:UUID 主键(`uuid.uuid4`);时间列 `DateTime` naive 本地时区(与 0060 迁移后基准一致,统一走 `_now()` 风格);子表 FK 一律带 `ondelete`(CASCADE/SET NULL 按语义)。
- 会话纪律:
  - 路由层用注入的 `AsyncSession`(与请求同生命周期);
  - 后台任务/独立事务用 `async with SessionLocal() as s` **短会话**,取数据即提交即释放,禁止长事务挂着;
  - **跨事件循环安全**:`SessionLocal` 连接池绑定 uvicorn 主 loop。任何运行在批处理线程临时 loop(`asyncio.run`)里的代码,禁止触碰全局 `SessionLocal`;需要入队/落库走 `fresh_session`,完成钩子回主 loop 用 `asyncio.run_coroutine_threadsafe`(参照 `wiki/generator.py` 的 `_spawn` 与 `enqueue_generation`)。
- 查询:列表接口先 `count` 再 `offset/limit`;筛选条件抽成模块内 `_xxx_conditions()` 供列表与批量操作**共用口径**(所见即所改)。

## 4. 错误处理规范

- **外部服务错误必须翻译后再落地**:LLM/MinerU/MinIO/ES 的原始报错(API JSON、英文堆栈)不允许直接透传给用户。参照 `wiki/generator.py::friendly_llm_error`——402 余额不足→\"请充值或在「模型配置」切换可用模型\",401→检查密钥,429→稍后重试;未知错误保留原文便于排查。翻译后的文案写入记录的 `error` 字段。
- **后台任务兜底**:任务主体 `try/except Exception` 全包,任何异常都要落到任务状态(`FAILED` + 中文原因),不允许静默吞掉或让任务永远停在 RUNNING;服务启动时恢复遗留 RUNNING(参照 `recover_interrupted_runs`)。
- 单条失败不阻断整批:批量操作逐条收集 `errors`,全部失败→FAILED,部分失败→COMPLETED+错误明细。
- 日志:模块级 `logger`;异常用 `logger.exception`;禁止 `print`;密钥/完整响应体不落日志。

## 5. 大数据量操作规范

- **破坏性批量操作必须可分批**:删除/清理类接口提供 `limit` 参数(单批 ≤500),前端循环调用、每批刷新进度;一次请求全量删除大表会造成长事务与前端超时。
- 逐条外部 IO(如 MinIO 删除)用 `await asyncio.to_thread(...)` 包裹,不阻塞事件循环。
- 分批消费的快照模式:入队合并 PENDING 记录,执行时每批快照 `BATCH_SIZE` 条、超出部分拆后续批(参照 `wiki/generator.py::_run_ingest`)。

## 6. 异步与并发规范

- 同库/同资源串行:进程内 `asyncio.Lock` 按资源 id 加锁(单进程模型);跨进程用 DB 行锁(`with_for_update`)。
- 后台任务派发统一走 `_spawn` 模式(主 loop `create_task`,临时 loop `run_coroutine_threadsafe` 回主 loop)。
- 阻塞调用(文件 IO、MinIO SDK、subprocess)必须 `to_thread`;Redis/PG 走 async 客户端。

## 7. 安全规范

- 密钥只存加密形态(参照 `kb_common/crypto.py`),明文仅签发时一次性返回;日志与 API 响应中脱敏。
- API Key 哈希入库,比对走常量时间校验。
- 内部服务间调用(如 faq-service → kb-api `/internal/embed`)带服务级密钥,不暴露公网。
- 上传/下载文件名校验与流式返回,不拼接 shell 命令。

## 8. 提交与验证门禁

- 改动完成后**必须** `uv run pytest tests/ -q` 全绿;涉及签名/路由行为变更同步更新测试(细则见 `docs/testing-spec.md`)。
- 新增配置项:同步 `.env` 模板(README)与 `kb_common/config.py`,写清默认值与缺省行为(fail-soft 优先)。
- 依赖新增必须写明理由;优先复用 `kb-common` 已封装客户端,禁止同能力第二套封装。

## 9. 自检清单(后端)

- [ ] 路由有鉴权声明;入参有 Pydantic/Query 校验
- [ ] 外部服务错误翻译为可行动中文;后台任务异常落状态不静默
- [ ] schema 变更有 alembic 迁移;批量删除支持分批
- [ ] 无跨 loop 使用 SessionLocal;阻塞 IO 走 to_thread
- [ ] pytest 全绿;错误分支有测试覆盖
