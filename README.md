# Knowledge Governance Expert（知识治理专家）

知识治理专家：文档采集 / 切片 / 向量检索 / LLM 问答 + FAQ 精准匹配 + **LangGraph 智能问答 Agent（基于 Dify 知识库）**，3 进程微服务 + Docker 基础设施 + 本地 Dify 服务。

## 架构

```
                     ┌─────────────────────────────────────────┐
   Web (Vue3)        │  本地原生进程（开发模式，BGE 在 Mac 内存）│
   :3000 (vite)      │                                         │
        │            │  kb-api:8000      FastAPI + BGE-M3      │
        │  /api/v1   │   ├ 文档/目录/检索/问答/认证/设置        │
        │  /api/v1/  │   ├ DeerFlow Runner (SSE 转译/回退)     │
        │   faq      │   ├ 内置 LangGraph Agent (回退工作流)   │
        └─────┬─────►│   └ /internal/embed (复用 BGE，无鉴权)  │
              │      │                                         │
              │ HTTP │  deerflow:2027  DeerFlow 2.0 sidecar    │
              │  SSE │   (Python 3.12 + uv，独立 venv)         │
              ├─────►│   ├ Lead Agent (create_agent 中间件链)  │
              │      │   ├ Sub-Agent 并行调研 / Todo 规划      │
              │      │   ├ 长期记忆 + 摘要压缩 + sqlite 检查点 │
              │      │   └ knowledge_search 工具 → kb-api 检索 │
              │      │                                         │
                     │  faq-service:8004 FastAPI (FAQ KB)      │
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
            └─────────────────────┬─────────────────────┘
                                  │ HTTP (Dify Service API)
            ┌─────────────────────┴─────────────────────┐
            │  Dify (本地 dify/docker，docker compose)    │
            │  nginx:8088 → api:5001 / web:3000          │
            │  内置 weaviate / postgres / redis / sandbox │
            │  知识库检索端点：POST /datasets/{id}/retrieve│
            └───────────────────────────────────────────┘
```

**4 应用进程**（kb-api / faq-service / kb-worker / **deerflow sidecar**）+ **5 基础设施容器**（dev-services compose）+ **本地 Dify 服务**（`dify/docker`，独立 compose，默认 8088 端口）。

BGE-M3 + bge-reranker-v2-m3 仅在 kb-api 进程加载一次（~2-3GB RSS），faq-service 与 kb-worker 经 `/internal/embed` 复用，避免 Mac 内存爆炸。

**智能问答 Agent 底座：DeerFlow 2.0 sidecar**。问答能力由真实的 [DeerFlow 2.0 Enhanced](https://github.com/stophobia/deerflow2.0-enhanced) harness 驱动（vendor 于 [services/deerflow/backend](services/deerflow/backend)），而非自建流程图。DeerFlow harness 要求 Python ≥3.12（langchain 1.2.x / langgraph 1.0.x），与 kb-api 的 Python 3.11 + langchain 0.x 无法同环境，因此以**独立 sidecar 进程**运行（端口 2027）：

- **进程内嵌入式运行**：sidecar 通过 DeerFlow 官方 `DeerFlowClient`（`deerflow/client.py`）在进程内直接跑 Lead Agent（create_agent + 中间件链 + 子智能体 + 长期记忆 + 摘要压缩 + sqlite checkpointer），**无需** langgraph server / gateway 进程。入口 [services/deerflow/backend/app/qa_server.py](services/deerflow/backend/app/qa_server.py)（FastAPI + SSE）。
- **配置自举**：sidecar 启动时 `GET` kb-api `/api/v1/agent/bootstrap` 拉取模型配置（base_url/api_key/model/temperature），自动生成 `config.yaml` 与「杰克百晓生」人格 `SOUL.md`；kb-api 晚启动时后台重试（40 次 × 5s）。
- **企业知识接入（目录预判 + 双来源检索 + 钉钉正文读取）**：DeerFlow 通过自定义扩展工具 [extensions/kb_tools.py](services/deerflow/backend/extensions/kb_tools.py) 挂载四个工具（`config.yaml` 的 `use: 模块:变量` 动态导入），知识类问题**主动、同时检索两个来源**，无需征询：
  - `knowledge_search` → kb-api `POST /api/v1/internal/kb/retrieve`（头 `X-Internal-Token`，env `KB_INTERNAL_TOKEN`，默认 `kge-internal-dev-token`），落到 Dify 语义+全文检索，返回文档正文片段，是答案内容的主要来源；
  - `dingtalk_browse` → kb-api `POST /api/v1/internal/dingtalk/browse`，**目录浏览**（不读正文、速度快）：`action="map"` 返回有权限知识库 → 二级目录的地图（含各目录文档/在线文档计数），用于**先预判问题最可能落在哪个知识库与目录**；`action="list"` 按目录关键词模糊匹配返回该目录下的文档（node_id/标题/扩展名/online 标记，**在线文档排在最前**）；
  - `dingtalk_search` → kb-api `POST /api/v1/internal/dingtalk/search`，基于钉钉知识库文件缓存（文件名/目录路径关键词匹配，见上文「钉钉知识」），用于目录预判不到时补漏，发现 Dify 未收录的文档；
  - `dingtalk_read_doc` → kb-api `POST /api/v1/internal/dingtalk/content`，通过 `dws` CLI 读取钉钉文档**正文**（在线文档 `dws doc read` 直读 Markdown；二进制文件 `dws drive download` 下载后**优先经本地 MinerU 引擎解析为 Markdown**——ppt/pptx/doc/docx/xls/xlsx 用 MinerU 原生 OOXML 转换（秒级、无需模型/LibreOffice），pdf/扫描件用 MinerU pipeline（OCR/版面/表格）；引擎不可用或返回空时降级 python-pptx/python-docx/openpyxl/pdfplumber 即时解析，再降级 MinerU 云 API）。**文件名/目录仅用于预判该不该读，答案必须基于正文**——pptx/docx 等办公文档正文可读后，智能体不再只靠文件名猜测内容。详见下文「文档解析引擎（本地 MinerU）」。
  - SOUL.md / SKILL.md 规定检索顺序：**先预判目录再进目录**（`knowledge_search` 与 `browse(map)` 并行 → `browse(list)` 列目录、在线文档优先精读、办公文档其次 → `search` 补漏），**每读完一篇立即确认能否回答**（能答即停，禁止无差别顺序读完整个目录），钉钉命中文档**必须读正文**再作答、禁止仅给链接；另规定双源穷尽检索（同义词/上下位词/拆解子问题，3-5 次以上）、多源结果归纳合并去重、答案第一句直接是实质内容；钉钉未配置时工具返回明确提示让智能体仅用 Dify 作答。
- **引用来源过滤**：[deerflow_runner.py](services/kb-api/app/services/agent/deerflow_runner.py) 的 `_filter_cited_citations` 在 `final` 事件前按答案正文过滤——只保留文档标题核心名（去 `[钉钉]` 前缀/扩展名/`杰克_` 前缀）出现在答案中的引用，避免把仅检索过但答案未提及的文档列出。
- **会话模型**：前端每个对话会话生成 `session_id`（重新对话时刷新），kb-api 映射为 DeerFlow `thread_id = kge-u{uid}-{sid}`；同一会话复用 sqlite 检查点维持多轮记忆与上下文。
- **限时探索机制（1 分钟询问 / 5 分钟再问 / 10 分钟兜底）**：由 [exploration_timeout_middleware.py](services/deerflow/backend/packages/harness/deerflow/agents/middlewares/exploration_timeout_middleware.py) 按 `thread_id` 跟踪墙钟（类级注册表，跨"暂停→续跑"保持），到点动作**确定性短路**（不依赖模型自觉、不额外消耗 token）：检索满 **1 分钟**未出答案时，`wrap_model_call` 直接合成一次 `ask_clarification` 工具调用（由 ClarificationMiddleware 拦截后结束本轮 SSE），前端弹出选择按钮「继续探索（再给我一些时间）/ 先基于已检索内容回答」；用户选继续后续跑，满 **5 分钟**仍无答案再问一次；总时长满 **10 分钟**则合成最终答复，明确告知"当前知识库无法获得准确答案"并建议换问法/知识征集。用户选「先基于已检索内容回答」时，`before_model` 注入停止指令给模型一次整合作答的机会，模型仍调工具则由 `after_model` 剥除并给兜底结论。阈值可用环境变量覆盖：`KGE_EXPLORE_FIRST_ASK`（默认 60s）、`KGE_EXPLORE_SECOND_ASK`（300s）、`KGE_EXPLORE_HARD_LIMIT`（600s）。
- **SSE 链路**：浏览器 → kb-api `/api/v1/search/chat/stream` → sidecar `/v1/chat/stream`（SSE）。[deerflow_runner.py](services/kb-api/app/services/agent/deerflow_runner.py) 把 DeerFlow 事件转译为前端协议：步骤事件（🦌 智能体 / 📚 知识检索(第N次) / 📌 钉钉知识库检索 / 📖 读取钉钉文档 / ✅ 检索完成 / 🧩 子任务派发 / 🙋 等待确认）+ `answer_delta` 流式文本 + `final`（答案/引用/追问/**usage token 用量**）；限时探索询问时额外下发 `choice`（问题+选项，渲染选择按钮）与 `choice_pause`（暂停收尾：本轮无 `final`，携带已耗 usage），用户点选后以同一 `session_id` + `action=continue|stop` 发起新请求续跑（[search.py](services/kb-api/app/routes/search.py) 的 `ChatIn.action` → runner → sidecar `ChatStreamIn.action` → `ExplorationTimeoutMiddleware.begin()`）。sidecar 侧按消息 id 去重并以首个状态快照建立历史基线避免重放；同时做**过渡独白 + 规划段落过滤**——工具调用前的 AI 思考文本按消息 id 缓冲并在确认 tool_call 后丢弃；最终答案消息完整缓冲到 values 快照到达，按段落剥离含"用户询问/已执行搜索/任务背景/node_id/工作空间"等关键词的规划段落后，再分块下发；被中间件强制收尾/剥除工具调用的答复由流末兜底逻辑保证必定下发，保证输出直接是答案正文、无内部分析过程。
- **优雅回退**：sidecar 不可达或未配置 LLM 时，kb-api 自动回退到内置 LangGraph 工作流（[workflow.py](services/kb-api/app/services/agent/workflow.py)：问题分类 → 改写 → Dify 检索 → 充分性判定 → 生成 / 深度探索），功能不中断。内置工作流同时是智能体配置页的数据源。
- **能力开关**：`planning_enabled`（Todo 规划中间件）、`subagent_enabled`（Lead Agent 并行派发 Sub-Agent 调研）、`long_memory_enabled`、深度思考等均在「智能体配置」页控制，随请求下发给 sidecar。

本地启动 sidecar：`bash scripts/start-deerflow.sh`（自动准备 Python 3.12 uv 环境）；Docker 全量模式下 `docker-compose.app.yml` 的 `deerflow` 服务自动启动（[services/deerflow/Dockerfile](services/deerflow/Dockerfile)）。

- **文档解析引擎（本地 MinerU）**：二进制办公/PDF 文档（ppt/pptx/doc/docx/xls/xlsx/pdf）由独立的 **MinerU 解析服务**统一转为 Markdown，供 `dingtalk_read_doc` 与本地文档入库 worker（[worker.py](services/kb-api/app/worker.py)）复用。服务为自托管 **MinerU 3.x `mineru-api`**（[scripts/start-mineru.sh](scripts/start-mineru.sh)，独立 venv `services/mineru/.venv`，端口 **2028**，与 DeerFlow sidecar 同模式）：`bash scripts/start-mineru.sh`（首次自动 `uv` 安装 `mineru[core]`；国内默认 `MINERU_MODEL_SOURCE=modelscope`，macOS Apple Silicon 自动 MPS、无 GPU 回退 CPU）。
  - **Office（pptx/docx/xlsx）走 MinerU 原生 OOXML 转换**，纯 Python 实现、秒级返回，**无需下载模型、无需 LibreOffice**；pdf/扫描件走 MinerU `pipeline`（版面/表格/OCR），首次解析时自动下载模型。
  - 调用链：kb-api [agent_internal.py](services/kb-api/app/routes/agent_internal.py) `/internal/dingtalk/content` 下载文件 → [mineru_client.py](services/kb-common/kb_common/clients/mineru_client.py) `parse()` **优先本地引擎**（`POST {MINERU_LOCAL_URL}/file_parse`，multipart `files` + `return_md=true` + `backend=pipeline`，取 `results[].md_content`，默认 `http://127.0.0.1:2028`，可用 env/`mineru_local_url` 关闭或改址）；本地不可用/返回空时**降级本地即时解析**（[agent_internal.py](services/kb-api/app/routes/agent_internal.py) `_local_parse`：python-pptx 逐页抽形状/表格/组合/备注、python-docx 段落+表格+文本框、openpyxl、pdfplumber），再降级 **MinerU 云 API**（需 `MINERU_API_KEY`）。健康检查 `GET http://127.0.0.1:2028/health`。
  - 效果：钉钉「战略报告.pptx」「经营计划 BP.docx」等可在 1–2 秒读出正文（含三大战略等关键内容），智能体据此基于**文档正文**作答而非文件名猜测。

**流式问答**：智能问答页支持 SSE 流式输出。DeerFlow 底座下实时显示 Lead Agent 运行进度（🦌 DeerFlow 2.0 智能体 → 📚 知识检索（第 N 次，含检索词）→ 📌 钉钉知识库检索/目录浏览 → 📖 读取钉钉文档 → ✅ 检索完成 → 🧩 子任务派发/返回 → 🙋 等待确认），回答文本通过 `answer_delta` 事件**逐字流式上屏**（不再等终帧）；回退内置工作流时显示原节点进度（🔍 分类 → ✏️ 改写 → 📚 检索 → ⚖️ 判定 → ✍️ 生成）。后端端点 `POST /api/v1/search/chat/stream`，前端 [chat/index.vue](web/src/views/chat/index.vue) 消费 SSE 事件逐条渲染步骤与增量文本。每个前端会话携带 `session_id`（重新对话时刷新）映射 DeerFlow thread。引用来源默认只展示前 5 条，超过可「展开全部」。模型下拉只显示系统配置中已配置可用的 LLM（未配置时显示占位引导）。

- **检索过程可展开**：助手消息的「智能体检索过程」步骤条运行中显示为紫色高亮条（spinner + 当前步骤 +「▸ 展开过程」），**点击即可展开查看全部步骤**（最后一步进行中带 spinner）；问答结束后步骤条仍可随时展开/收起，便于回溯检索路径。注意轮次保存后仅刷新侧边栏会话列表，不用 DB 记录全量重载消息，以保留按钮/Token 等交互态。
- **限时探索选择按钮**：检索超 1 分钟（继续后再超 5 分钟）时，助手消息中出现选择卡片（`choice`/`choice_pause` 事件），提供「继续探索（再给我一些时间）/ 先基于已检索内容回答」两个按钮：点继续则以 `action=continue` 在同一 thread 续跑；点停止则 `action=stop` 立即收尾作答；按钮点击后禁用。10 分钟硬上限由系统自动给出"当前知识库无法获得准确答案"的兜底回复。
- **Token 消耗展示**：消息时间行在模型名/时间之后显示本轮模型接口返回的真实用量（`· ↑{input_tokens} ↓{output_tokens} tokens`，≥1000 紧凑显示为 x.xk），数据取自 sidecar `end` 事件的 `usage`（按各模型轮次 `usage_metadata` 累计），经 runner `final.result.usage` / `choice_pause.usage` 透传到前端。
- **多会话并行问答（切换不中断，最多 5 路）**：不同会话可同时问答，**切换会话不中断进行中的回答**。前端 [chat/index.vue](web/src/views/chat/index.vue) 用会话级运行注册表 `runs`（sid → 消息对象/abort/状态）与内存消息数组 `liveArrays` 持有各会话的 SSE 连接与流式消息——连接归属会话而非视图，切换会话仅替换 `messages` 引用，后台会话继续逐字上屏，切回即恢复现场；当前会话是否「运行中」由 `loading` 计算属性派生。侧栏会话条目状态指示：运行中=**旋转小圆圈**（`.run-spinner`）、等待确认（choice_pause 暂停）=**琥珀点**（`.run-choice-dot`，回会话点选继续/停止）、有新完成的回答=**绿点**（`.run-done-dot`，打开该会话即清除）。并发上限 `MAX_CONCURRENT=5`（等待确认的 choice 态不占后端并发），超出发送提示稍候；同一会话运行中不允许重复发送。仅「停止按钮」与「删除会话」会 abort + cancel 对应会话。实现要点：`reactive(new Map())` 读取值是响应式代理，与原始对象严格比较恒为 false，运行态身份判断必须经 `toRaw` 归一（`isRun` 辅助函数），否则转圈不落点、完成不清理。后端配套：sidecar 的全局 `_stream_lock` 改为 `_NullLock`（仅保留结构），并发由 `_serialize_checkpointer` 给 SqliteSaver 各方法挂**方法级 `threading.RLock`**（可重入，规避 `get_tuple`→`setup` 嵌套自锁）实现——多会话的 LLM 流式长任务完全并行，仅 sqlite 检查点短 IO 在共享连接上串行；多会话同时读钉钉文档时 [agent_internal.py](services/kb-api/app/routes/agent_internal.py) `_run_dws` 全局并发≤3 + 0.4s 节流 + 瞬时失败重试 1 次，避免并行限频 500。
- **运行中可中断（停止按钮 + 后端真正停止 Agent）**：回答进行中发送按钮变为深色实心方块（停止按钮），点击即中断；中断后按钮恢复发送态，末条 AI 消息标记「⏹ 已中断 · {model}」（无正文时补「（已中断本次回答）」）。中断采用**双保险**：前端除 `abort` 断开 SSE 外，额外 `POST /api/v1/search/chat/cancel`（[chat.ts](web/src/api/chat.ts) `cancelChat`），kb-api 按同一规则拼 `thread_id` 调 sidecar `POST /v1/chat/cancel`（[deerflow_runner.py](services/kb-api/app/services/agent/deerflow_runner.py) `cancel_deerflow_stream`），确保取消信号确定性到达、不依赖断连检测时机。后端确定性停止：① [exploration_timeout_middleware.py](services/deerflow/backend/packages/harness/deerflow/agents/middlewares/exploration_timeout_middleware.py) 的 `cancelled` 标志在每个模型节点边界由 `wrap_model_call` 短路（**不再调用模型、不耗 token**），`_due_action` 中 cancelled 优先级最高；② sidecar 收到取消后在**驱动 agent 的同一线程** `gen.close()` 注入 `GeneratorExit`，关闭同步图迭代器，中断进行中的模型流并释放资源。sidecar `/v1/chat/stream` 用**专属 worker 线程 + `asyncio.Queue` 泵**驱动**同步** `agent.stream()`（DeerFlow harness 用同步 `SqliteSaver`，不支持 `astream`/`AsyncSqliteSaver`）：worker 线程在 loop 外迭代同步生成器、把帧 `call_soon_threadsafe` 入队，async 泵端出帧下发；泵每 0.2s 轮询 `is_cancelled(thread_id) or request.is_disconnected()`，使取消发生在「等帧间隙」（无帧可触发）或**纯断连**（不调 cancel 直接关页/杀连接）时也能被检测并停图。`gen.close()` 始终在同一 worker 线程的 finally 中执行，保证 checkpointer 串行锁必被释放（多会话并发后 `_stream_lock` 退化为 `_NullLock`，sqlite 串行由 `_serialize_checkpointer` 的方法级 RLock 承担，见「多会话并行问答」）——中断后立即发新问答不卡锁、不回退内置工作流。sidecar 下发 `{"type":"cancelled"}` 帧，runner 收到即 `return`（跳过追问生成/`final`），kb-api `_gen` 的 finally 兜底再 cancel 一次（正常结束为 no-op）。注意 anyio 的 `CancelScope` 是**同步**上下文管理器，收尾时必须用 `with anyio.CancelScope(shield=True):`（`async with` 会抛 `TypeError` 导致 close 不执行、图被遗弃在后台继续跑空转耗 token）。同步工具（`@tool` 知识库/钉钉检索，httpx 同步、在 executor 线程跑）无法即时取消但会自然结束且不再驱动图；模型调用是 async httpx（token 消耗源），由中间件短路 + close 迭代器在「下一个图事件」粒度（通常 1～数秒）停止。

**HiAgent 智能问答（外链嵌入）**：侧边栏「HiAgent智能问答」页通过火山引擎 HiAgent WebSDK（`embedFull.js`）以 iframe 方式内嵌官方智能体对话界面，见 [hiagent/index.vue](web/src/views/hiagent/index.vue)。SDK 以初始化内联脚本的父节点作为挂载容器，前端在 `onMounted` 时把 SDK 脚本与 init 脚本动态注入页面宿主 div，离开页面时清理 iframe；appKey/baseUrl 常量定义在该视图文件顶部。

**「关于我」产品介绍页**：侧边栏左下角「关于我」按钮（紫色图标，所有登录用户可见，[Sidebar.vue](web/src/components/layout/Sidebar.vue)），点击**新开浏览器页签**打开纯静态介绍页 [web/public/about.html](web/public/about.html)（原生 `<a :href="import.meta.env.BASE_URL + 'about.html'" target="_blank">`，避免弹窗拦截；dev 与构建产物均由根路径直达，不依赖登录态与后端）。页面以营销页形式呈现：平台定位与数据条（4 应用进程 / 5 基础设施容器 / 1.6万+ 钉钉知识节点 / 6.7TB 企业存储 / 1/5/10min 限时探索）、设计理念（答案优先而非链接堆砌、先预判目录再进目录、把时间还给用户、一切皆可配置、安全与稳定是默认值、基于正文作答）、**知识治理闭环全景图**（单张紧凑白色卡片，SVG 环形闭环布局：5 个彩色圆角节点①采集「汇得拢」②加工「读得懂」③应用「用得上」④运营「看得见」⑤治理「管得住」围成圆环，灰色实线弧箭头沿环顺时针流转，**治理→采集的橙色收口弧使首尾相接成闭环**；环中心为紫色「治理飞轮」hub（越用越准·越治越新）；环内两条红色虚线表达跨环节质量回流——治理→加工（重分段/重打标/重建索引）、应用→治理（问答反馈·点赞/踩/无结果），回流标签最后绘制并加白色描边保证压线可读；卡片底部双行图例（环节色点 + 线条类型）；≤960px 窄屏自动降级为纵向紧凑列表）、闭环整体价值三胶囊（知识不沉没/质量自进化/投入可度量）、分层系统架构图（接入层 → DeerFlow 智能体层 → 应用服务层 → 检索与解析 → 基础设施）、八大功能模块卡片与技术亮点清单；内容与 README 架构章节保持同口径（HiAgent 为临时模块未收录）。纯单文件 HTML + 内联 CSS，无外部资源依赖，响应式适配窄屏。

## 两种运行模式

### 模式 1（推荐）：本地原生 + Docker 基础设施

应用进程跑在 Mac 原生内存（BGE 模型直接用 Mac RAM），基础设施跑在 Docker。**开发期推荐**，迭代快，无需 colima 加内存。

```bash
# 1. 启动 Docker 基础设施（dev-services compose，一次性；路径按实际调整）
docker compose -f ~/Documents/03_Resource/开发环境/docker-compose.yml up -d

# 2. 配置 .env（仓库根目录，参考下方 .env 配置）

# 3. 安装依赖（每个服务首次）
cd services/kb-common && uv sync && cd -
cd services/kb-api && uv sync && cd -
cd services/faq-service && uv sync && cd -

# 4. 初始化数据库表 + 种子 admin
cd services/kb-common && uv run alembic -c ../../alembic.ini upgrade head
cd services/kb-common && uv run python ../../scripts/seed_admin.py
# admin / admin123

# 5. 启动 4 个应用进程（各开一个终端）
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
cd services/kb-api && uv run celery -A app.worker worker -Q ingestion --concurrency=2 -l info
cd services/faq-service && uv run uvicorn app.main:app --reload --port 8004
bash scripts/start-deerflow.sh       # DeerFlow 2.0 QA sidecar:2027（首次自动 uv 准备 Python 3.12）
bash scripts/start-mineru.sh         # 本地 MinerU 文档解析引擎:2028（首次自动 uv 安装 mineru[core]；解析 ppt/pptx/docx/xlsx/pdf 正文）
# 不启动 sidecar 也可问答：kb-api 健康检查失败时自动回退内置 LangGraph 工作流
# 不启动 MinerU 也能读办公文档：自动降级 python-pptx/python-docx 等即时解析（图片型/扫描件效果弱于 MinerU）

# 6. 启动前端
cd web && pnpm install && pnpm dev   # http://localhost:3000
```

登录：`admin` / `admin123` (super_admin)。

### 模式 2：Docker 全量模式（需基础设施已启动）

**前提**：基础设施（dev-services compose）必须已启动，参考模式 1 步骤 1。

```bash
# 启动应用服务（kb-api / faq-service / kb-worker / deerflow sidecar）
docker compose -f docker-compose.app.yml up -d --build
```

> **⚠ colima 内存要求**：BGE-M3 在 kb-api 容器内 CPU 推理，需 colima ≥ 8GB：
> ```bash
> colima stop && colima start --cpu 4 --memory 8
> ```
> 首次启动较慢（BGE 模型下载 ~2GB，容器内首次 embed 约 30-60s）。MVP 不推荐此模式做开发，仅用于验证镜像可部署。

清理应用容器（不清理基础设施）：
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
# MinerU（可选 - 配置 Key 后支持 PDF/DOCX/PPTX/XLSX/HTML 云解析；未配置仅本地解析 txt/md/csv）
MINERU_API_KEY=
# Dify 知识库（智能问答 Agent 使用；Service API 端点需含端口与 /v1）
DIFY_BASE_URL=http://127.0.0.1:8088/v1
DIFY_API_KEY=
DIFY_DATASET_IDS=
```

**Dify 配置说明**：
- `DIFY_BASE_URL`：Dify **Service API** 端点，必须同时包含端口与 `/v1`，如本地 `http://127.0.0.1:8088/v1`（见下方 [Dify 知识库服务](#dify-知识库服务)）。注意不是控制台地址 `http://127.0.0.1:8088`（少 `/v1`）也不是 `http://127.0.0.1/v1`（少端口），两者都会导致数据集列表/检索失败。
- `DIFY_API_KEY`：Dify Dataset API Key（如 `dataset-R6qPqf7CfPC0Dbn6uT3LxIKw`）。留空则智能问答走本地 ES 知识库；配置后走 LangGraph Agent + Dify 检索。可在「系统配置」页运行时配置。
- `DIFY_DATASET_IDS`：默认检索的 Dify 数据集 ID，逗号分隔；问答页未选数据集时使用。可在配置页「拉取列表 → 填入全部 ID」自动填入。

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
- `MINERU_API_KEY` 配置后 -> PDF/DOCX/PPTX/XLSX/HTML 走 MinerU 云解析；留空 -> 仅 txt/md/csv 本地解析兜底，二进制格式会抛「解析 {ext} 需配置 MINERU_API_KEY」（可在「平台管理 -> 模型设置」页运行时配置，密钥落地 settings 表，GET 接口掩码 `value=""` + `is_set=true`）。

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
| 问答提示「尚未配置 LLM API Key」 | 智能问答依赖 LLM；在「系统配置 → 接入配置」填 LLM API Key 并保存，或在 `.env` 配 `LLM_API_KEY`。Agent 未配置时返回 `config_error=llm_not_configured`（不再 500），前端在对话气泡给出跳转按钮 |
| PDF/DOCX 解析失败 | 配置 `MINERU_API_KEY` 后支持 PDF/DOCX/PPTX/XLSX/HTML 云解析；留空则仅 txt/md/csv 本地解析，二进制格式抛「需配置 MINERU_API_KEY」 |
| `uv sync` 报 `kb-common` 找不到 | 在 `services/kb-common` 先 `uv sync`；Docker 构建已通过 repo-root context 解决 |
| 端口 8000/8004 被占用 | `lsof -i :8000` 找到进程；或改 uvicorn `--port` |
| dev-network 不存在 | 先启 dev-services compose：`docker compose ls` 找配置文件 |
| Dify 镜像拉取 EOF | Docker Hub CDN 间歇中断；用 `bash dify/docker/pull-images.sh` 单镜像重试续传，或重跑 `docker compose up -d` |
| Dify 数据集列表 502/连接失败 | Dify `API 端点` 必须含端口与 `/v1`：本地为 `http://127.0.0.1:8088/v1`。填成 `http://127.0.0.1/v1`（缺端口）或 `http://127.0.0.1:8088`（缺 `/v1`）都会失败；在「系统配置」的 Dify 配置编辑弹窗中更正并重新「启用」 |
| 智能问答数据集为空 | 先在 Dify 控制台创建知识库并上传文档，再到「系统配置 → 接入配置」填 Dify `API 端点`/`API Key` 并「拉取列表」 |
| 8088 端口被占用 | 改 `dify/docker/.env` 的 `EXPOSE_NGINX_PORT`，并同步改 kb-api 的 `DIFY_BASE_URL` |
| Dify 控制台 502 Bad Gateway | nginx 启动早于 api 就绪会缓存错误上游 IP（macOS 代理 fake-ip `198.18.x.x`）；`docker restart docker-nginx-1` 强制重解析即可。若 api 日志报 `No space left on device`，先 `docker system prune -a -f` 清理 colima 磁盘 |
| HiAgent 页提示「当前域名无访问权限」 | HiAgent 智能体配置了网站访问白名单（WebSiteList）；到 HiAgent 控制台把当前访问域名（如 `http://localhost:5173`）加入 WebSDK 嵌入白名单，或清空白名单允许所有域名 |
| HiAgent 页一直加载/脚本加载失败 | 需能访问外网 `hia.volcenginepaas.com`；公司网络拦截时放开该域名，或检查 appKey 是否有效（appKey/baseUrl 在 [hiagent/index.vue](web/src/views/hiagent/index.vue) 顶部常量维护） |

## 智能问答交互（前端）

问答页 `web/src/views/chat/index.vue` 按聊天式设计稿实现，品牌色 `#6157FF`（紫蓝），设计令牌仅在本页 scoped 生效，不改全局主题。聊天卡片铺满后台内容区（去掉 `max-width` 居中约束，`height:100%` flex 撑满），头部与输入区固定、消息区 `.chat-scroll` 内部滚动；欢迎语垂直居中，提问后消息从顶部开始排列（首条问题在右上角），流式步骤/答案追加时自动滚动到底部：

- **头部助手身份卡**：紫色渐变圆形头像 + 名称「杰克百晓生」+ 在线状态点（空闲绿色 / 思考中橙色脉冲），右上角「重新对话」按钮清空消息回到欢迎态。
- **欢迎空状态**：居中标题「你好！有什么可以帮你的吗？」+ 副标题；Dify 未配置时显示黄色引导条。
- **消息气泡**：用户消息右侧（灰色圆形头像 + 浅灰气泡 + 时间戳），助手消息左侧（紫色渐变头像 + 浅紫气泡）。助手回答前先显示三个紫色跳动圆点（typing），随后实时展示 LangGraph 步骤（🔍 分类 → ✏️ 改写 → 📚 检索 → ⚖️ 判定 → ✍️ 生成）。
- **引用来源**：按文档去重（同一文档只显示一条），默认展示前 5 条可展开；答案/引用/反馈条都在气泡内。
- **消息操作**：用户消息 hover 显示「复制 / 编辑」（编辑把内容填回输入框），助手答案 hover 显示「复制」，图标仅 hover 时出现。
- **建议问题**：横向滚动胶囊按钮，hover 上浮变紫。
- **输入区**：圆角大容器（focus 时紫色 ring），上方工具条三个开关/选择器，下方无边框 textarea + 圆形发送按钮（有内容时变紫）：
  - **模型选择**：下拉只列出「系统配置」中已配置的可用模型；选中模型随请求 `model` 字段传给后端，覆盖系统默认模型（占位项「（未配置 LLM）」不覆盖）。
  - **深度思考**：开关，随 `deep_think` 传后端。开启后知识库召回 `top_k` 由 5 提升到 10，生成节点温度调高并追加「分步拆解、逐一引证、详尽回答」指令；助手消息 meta 前缀显示「深度思考 ·」。
  - **知识库检索**：开关 + 数据集多选弹层。开启时按勾选的 Dify 数据集检索（`dify_dataset_ids`），可全选/半选；关闭时传 `null` 走系统默认数据集。
- **流式**：`POST /api/v1/search/chat/stream`（SSE）逐节点推送 `step` / `answer_delta`（回答文本增量，逐字上屏）/ `final`（含 `usage` token 用量）/ `choice` / `choice_pause`（限时探索确认按钮，本轮无 `final`）/ `config_error` 事件；`ChatIn` 支持 `model` / `deep_think` / `history` / `session_id`（映射 DeerFlow thread，重新对话时刷新）/ `action`（限时探索续跑：`continue` 继续探索、`stop` 立即收尾，留空为新问题）参数（非流式 `/chat` 同步支持）。
- **下一步问题建议**：回答完成后，答案反馈条下方显示「你可能还想问」3 个追问胶囊（由模型生成，点击直接提问）。

## 智能体配置（DeerFlow 2.0 底座）

问答智能体以开源 [DeerFlow 2.0 Enhanced](https://github.com/stophobia/deerflow2.0-enhanced) harness 为 Agent 底座（Lead Agent 中间件链 + 子智能体 + 长期记忆 + sqlite 检查点，详见上方「架构」章节）；内置 LangGraph 工作流（Planner/Researcher/Reporter 思路：规划 → 检索 → 反思循环 → 报告）作为 sidecar 不可用时的回退与配置数据源，全部行为由配置驱动。配置入口在**侧边栏左下角「智能体配置」**（紫色图标，管理员可见，路由 `/agent-config`），配置以 JSON 存于 settings 表（key=`agent_config`），并通过 `/api/v1/agent/bootstrap` 下发给 DeerFlow sidecar 生成 `config.yaml`。

**后端工作流**（[workflow.py](services/kb-api/app/services/agent/workflow.py)）：

```
问题分类 → ├ 模糊 → 澄清 → END
          ├ 无关 → 拒答 → END
          ├ 闲聊问候（智能模式）→ 寒暄直答 → 追问建议 → END
          └ 业务问题 → 改写 → 任务规划(复杂/深度) → 知识检索
                 → 充分性判定 ┬ 充分 → 生成答案(Reporter)
                             ├ 不足且未超轮数 → 查询反思改写 → 回到检索（Researcher 反思循环）
                             └ 超轮数 → 深度探索
                 → 下一步问题建议(可选) → 保存上下文
```

**配置项**（`GET/PUT /api/v1/agent/config`，`GET /api/v1/agent/greeting`）：

| 分组 | 配置 | 说明 |
|------|------|------|
| 基础 | 模型 models | 参与调度的模型（最多 10），问答页下拉优先使用；为空用系统默认 LLM |
| 基础 | 知识库 retrieval_mode | `smart` 智能调用（闲聊直答不检索）/ `force` 强制调用（每问必检索） |
| 基础 | 对话开场白 | 开关 + 欢迎语 + 推荐问题（最多 6），问答页欢迎区读取 |
| 基础 | 下一步问题建议 | 回答后生成 3 个「你可能还想问」追问 |
| 高级 | 任务规划 planning_enabled | 复杂/深度问题先由 Planner（DeerFlow Todo 中间件）拆解计划 |
| 高级 | 子智能体协作 subagent_enabled | DeerFlow Lead Agent 将复杂问题并行派发 Sub-Agent 分头调研再汇总（更全面但更慢更耗 Token） |
| 高级 | 长期记忆 long_memory_enabled | 携带多轮对话（DeerFlow thread 检查点 + 摘要压缩），支持指代追问 |
| 高级 | 默认深度思考 deep_think_default | 新会话默认开启深度思考 |
| 超参 | temperature / top_p / max_tokens | 生成温度、核采样、最大输出 token |
| 超参 | top_k | 知识库召回条数（深度思考自动提升至 ≥10） |
| 超参 | max_retrieval_rounds | 检索反思轮数（1-4），资料不足时换角度重检 |

**人格与技能（SOUL.md / SKILL.md）**：「智能体配置 → 人格与技能」Tab 提供两个提示词编辑器，可在线修改 DeerFlow 运行时的**系统人格**（身份/职责/双源检索策略/作答规范）与**问答技能**（企业知识库问答工作流指令，含 name/description/version frontmatter）：

- 链路：前端 `GET/PUT /api/v1/agent/persona`、`/api/v1/agent/skill`（管理员）→ kb-api 代理（X-Internal-Token）→ DeerFlow sidecar `GET/POST /v1/persona`、`/v1/skill`（[qa_server.py](services/deerflow/backend/app/qa_server.py)）。
- **热生效**：保存后 sidecar 立即重写运行时文件并 `reset_client()` 重建 Agent，新对话即时生效；进行中的会话不受影响。
- **持久化**：自定义内容存于 `DEER_FLOW_HOME/persona.custom.md`、`skill.custom.md`，sidecar 重启/重载时优先使用自定义文件；默认模板内置于 qa_server.py（`SOUL_MD`/`SKILL_MD` 常量），点「恢复默认」即删除 custom 文件并恢复模板；SKILL.md 同步写入 `services/deerflow/skills/custom/enterprise-kb-qa/SKILL.md`。

前端配置页 `web/src/views/agent/config.vue` 仿智能体平台卡片式布局（基础设置/高级设置/人格与技能三个 Tab + 折叠卡片 + 开关/单选/滑块 + 等宽字体提示词编辑器）。

## Dify 知识库服务

本项目内置一份 Dify 源码（`dify/` 子目录，原版 1.16.1），用 Docker Compose 本地启动，作为智能问答 Agent 的知识库检索后端。

### 启动 Dify

```bash
cd dify/docker
# 首次：.env 已预配（INIT_PASSWORD=Dify@2026、EXPOSE_NGINX_PORT=8088）
docker compose up -d
```

启动后：
- Dify 控制台：http://127.0.0.1:8088 （首次用 `admin` / `Dify@2026` 登录设置）
- 内部服务（api:5001 / web:3000 / weaviate / postgres / redis / sandbox / plugin_daemon / agent_backend）在 compose 网络内互通，仅 nginx 8088 暴露到主机
- 镜像拉取受网络影响时，跑 `bash dify/docker/pull-images.sh` 单镜像重试续传

### 获取 Dify API Key

1. 登录 http://127.0.0.1:8088 → 「知识库」新建一个 Knowledge Base → 上传文档/导入内容
2. 进入该知识库 → 左侧「API」分页 → 复制右上角 **Dataset API Key**（形如 `{...}`）
3. 多个知识库可在同一 Dataset API Key 下管理（App/Console Key 也可，需有多数据集权限）

### 配置 Dify 模型供应商（语义检索必需）

Dify 知识库的**语义检索/混合检索**在查询时要用 Embedding 模型把问题向量化。若 Dify 未配置默认 Embedding 模型，检索接口返回 `400 Default model not found for text-embedding`（本项目客户端会自动降级为全文检索，不报错，但高质量索引的文档可能无命中）。

在 Dify 控制台（http://127.0.0.1:8088）：
1. 右上角「设置 → 模型供应商」配置一个 OpenAI 兼容的 Embedding 模型（如 OpenAI / 本地网关的 `text-embedding-3-small`、`bge-m3` 等）
2. 在「设置 → 模型供应商 → 默认模型」中将其设为系统默认 **Embedding 模型**（如用重排，再设默认 Rerank 模型；未设时本项目 `dify_reranking_enable` 默认 false）

### 接入到本项目

在「系统配置」页（路由 `/model`）：
1. 在「Dify 知识库」处「新增配置」：`API 端点` = `http://127.0.0.1:8088/v1`（**必须含端口与 `/v1`**）→ 保存
2. `API Key` = 上一步复制的 Dataset API Key（形如 `dataset-xxx`）→ 保存
3. 点「拉取列表」→ 数据集表格出现 → 点「填入全部 ID」→ 「数据集 ID」框自动填入 → 「启用」该配置（启用后同步为系统生效值）
4. 回到「智能问答」页 → 下拉框自动加载并全选数据集 → 提问即走 LangGraph Agent

> **智能问答同时依赖 LLM 与 Dify**：分类/改写/判定/生成都要调 LLM。若未配置 `LLM_API_KEY`，问答不再报 500，而是返回 `config_error=llm_not_configured`，前端在对话气泡中提示「请前往系统配置填写 LLM API Key」并带跳转按钮；Dify 地址配错时数据集列表会显示 `Dify 返回 5xx/4xx：…` 错误。

> 也可直接在仓库根 `.env` 写 `DIFY_BASE_URL` / `DIFY_API_KEY` / `DIFY_DATASET_IDS` 启动时注入。

### 知识流水线（RAG Pipeline）文档解析分流

流水线知识库按文件类型自动选择解析引擎（直接改 `workflows` 表图 JSON 实现，draft 与 published 全部生效）：

```text
File Upload (datasource)
  → 文件类型分流 (if-else: file.extension in [.pdf .ppt .pptx .doc .docx .png .jpg .jpeg])
      ├─ true  → MinerU (langgenius/mineru parse-file)
      └─ false → Dify Extractor (langgenius/dify_extractor)
  → 提取结果聚合 (variable-aggregator, 取两分支 .text)
  → Parent-child Chunker → Knowledge Base
```

- MinerU 引擎为本机 `services/mineru`（mineru-api 3.4.5，端口 2028），仅支持 pdf/docx/pptx/xlsx/图片；**不支持 .doc/.ppt/.xls 老格式**
- **.doc/.ppt/.xls 老格式**已在 `services/mineru/.venv/lib/python3.12/site-packages/mineru/cli/fast_api.py` 打补丁：上传时自动转对应 OOXML 格式再解析（`LEGACY_OFFICE_CONVERSIONS` + `_convert_legacy_office`）。转换器跨平台：**优先 LibreOffice（soffice），服务器部署必须 `apt-get install -y libreoffice-writer`**；macOS 本地开发对 .doc 回退 textutil。重装 venv / 升级 mineru 包后需重新应用补丁
- txt/md/xlsx/csv/html/json/yaml 等走 Dify Extractor（纯文本抽取，PDF 走 MinerU 获得更好的版面/表格/公式识别）

### 停止 / 清理

```bash
cd dify/docker
docker compose down            # 停止并删除容器（保留卷与镜像）
docker compose down -v        # 同时删除卷（清空 Dify 数据库与知识库，慎用）
```

## 知识中心

「知识中心」（路由 `/knowledge-center`）提供统一的知识文件列表视图，分两个一级 Tab：

### 钉钉知识

实时拉取**钉钉开放平台**的企业知识库（Wiki）数据，非本地数据：

- **数据源**：`dingtalk_client` 调用 `v2.0/wiki/workspaces` + `v2.0/wiki/nodes` 遍历操作人可见的全部团队知识库；创建人 userid 经 `oapi.dingtalk.com/topapi/v2/user/get` 解析为姓名（进程级缓存）。
- **上级目录**：多层文件夹以 `/` 拼接完整路径（如 `/业务管理/AI与数字化团队/营销项目管理/M8系统`），知识库根目录下的文件显示 `/`。
- **元数据列**：文件名称（点击跳转钉钉文档）、来源知识库、上级目录、文件类型、文件大小、创建人、创建时间、最近更新。
- **过滤维度**：按知识库过滤（多选）、按创建人过滤（多选）、文件名搜索、上级目录路径搜索。
- **手动刷新**：右上角「刷新」触发后台重新遍历钉钉；结果内存缓存 1 小时，遍历成功后同时落盘快照（`/tmp/kge_dingtalk_files.json`，可用环境变量 `KGE_DINGTALK_SNAPSHOT` 覆盖路径）。进程重启 / 开发环境 `--reload` 后自动从快照预热，无需等待全量遍历。
- **性能与容错**：钉钉 `wiki/nodes` 接口限流严格（实测 3 并发即批量 403），客户端采用**并发信号量（≤3）+ 全局最小请求间隔节流（0.4s/次，约 2.5 QPS）+ 403/429/5xx/超时指数退避重试**；遍历为后台异步任务（单飞，并发访问不重复遍历），前端按 12s 间隔轮询，全量约 4,500 个节点请求、25–30 分钟；明确无权限的目录自动跳过。
- **配置**：在「系统配置」页填写钉钉 AppKey / AppSecret / 操作人 UnionId（settings 表持久化，`sync_runtime_config` 每次调用前同步）；未配置时页面显示友好告警。

### 本地上传知识

平台内上传的文档（DOCUMENT 类型知识库），平铺列表展示：

- **元数据列**：文档标题、来源知识库、知识分类、文件类型、文件大小、分块数、状态、创建人、创建时间。
- **过滤维度**：按知识库过滤（多选）、按创建人过滤（多选）、标题关键词搜索。
- **手动刷新**：右上角「刷新」按钮；任务队列状态栏展示 全部/执行中/已完成/失败 计数。
- 创建人通过 `documents.uploader_id` 关联 `users` 表（迁移 `0005_add_document_uploader` 新增；历史文档显示 `-`，新上传自动记录）。

## 知识运营（原运营看板）

侧边栏「知识运营」（路由 `/operate`）含三个页签：

- **运营看板**（后端 `app/routes/operate.py`）：知识存储总量/知识数量/热门知识 Top20 的定时统计与持久化。
- **问答明细**（后端 `app/routes/qa_route.py`，`GET /api/v1/qa/details`）：真实问答流水，块状列表展示用户、问题、回答链路（分类→改写→检索→判定→生成 steps）、召回片段（Score 进度条/文档名/片段内容/片段ID）、点赞/点踩反馈标签；支持按检索时间、检索内容（问题/回答关键词）、用户、反馈类型多维过滤与分页。数据来源：`chat_messages` 表，问答完成时由前端持久化 `detail`（链路 steps + 召回片段快照 + 模型）。
- **知识纠错**（`GET/PUT /api/v1/qa/corrections`）：用户在问答页提交的纠错工单（`qa_feedbacks` 表，feedback_type=correct，错误类型含内容错误/知识重复/知识过期/知识难理解/知识不完整/知识模板错误/其它）；支持按知识标题、错误类型、状态过滤，管理员可处理（处理人自动记录、处理备注、状态流转 待处理→处理中→已解决/已关闭）。**知识标题可点击跳转原文**：钉钉文档（alidocs.dingtalk.com 链接）跳转钉钉知识库对应文档，Dify/本地文档跳转预览页；无链接的历史工单显示纯文本。

问答页反馈按钮（👍有帮助 / 👎纠错 / ❓没找到想要的）已全部接入真实接口（`POST /api/v1/qa/feedback`），点赞/没找到直接记录。**引用来源旁的「👎 纠错」按钮**可针对单条知识纠错：点击后自动带入该条知识的名称与链接（`knowledge_title`/`knowledge_url`，存入 `qa_feedbacks`，alembic 0010），弹窗中可直接打开原文链接核对；反馈栏的通用纠错按钮不带具体链接。引用来源的文档名本身也可点击（有外链时新窗口打开原文）。

### 运营看板指标口径

**统计机制与持久化（流水表）**

- **定时统计**：知识存储总量、知识数量（含分布）、热门知识 Top20 由 kb-api 内置调度器**每日 0 点自动统计**；也可点「刷新」按钮手动触发。统计流程：存储（秒级）→ 知识库全量遍历（约 30 分钟）→ 热门逐文档统计（约 30 分钟）。
- **持久化**：每个指标统计完成即写入流水表 `operate_metric_records`（alembic 0006，metric_key / metric_date / value(JSON) / trigger(daily|manual) / created_at），保留 180 天。
- **展示**：接口取各指标**最新一条流水**返回（内存快照镜像）；服务重启后自动从流水表恢复；若当天无记录（如 0 点时服务重启错过定时），启动后自动补统计。
- 知识召回数 / 调用量仍为「即将发布」，待知识采集流程打通、Dify 文档关联钉钉文档 ID 后基于 `usage_logs` 统计。

| 指标 | 数据来源 | 口径说明 |
| --- | --- | --- |
| **知识存储总量** | 优先钉钉企业存储 API `GET /v1.0/storage/orgs/{corpId}`；权限不足时自动降级**钉钉官方 CLI**（`tools/dws/dws`，`drive quota apps`） | 与钉钉知识后台口径**一致**：全应用存储用量汇总（钉盘 2.4TB + 钉钉文档 1.7TB + 会议 1.4TB + AI 听记等 19 个应用，当前约 **6.7TB**）。API 需应用开通「企业存储企业读权限 `Storage.Org.Read`」；CLI 走 `dws auth login` 扫码的**用户 OAuth 授权**，与应用权限相互独立，结果缓存 10 分钟。两条路都失败时回退为"仅文件大小"（约 0.8TB，在线文档 size=0 不可见） |
| **知识数量** | 遍历 `v2.0/wiki/nodes` 统计团队知识库文件节点 | 后台异步全量遍历 + 内存缓存（TTL 1 小时），首次约 25–30 分钟，前端 20 秒轮询。当前全量约 1.6 万个文件节点 |
| **企业知识数量分布** | 同上，按知识库聚合 | echarts 环形饼图 |
| 知识召回数 / 调用量 | 暂不取数 | 待知识采集流程打通、Dify 文档关联钉钉文档 ID 后统计，显示「即将发布」 |
| **热门知识 Top20** | 逐文档调用钉钉 CLI `dws drive stats`（阅读/访问/编辑/评论统计） | 按**访问次数**倒序（相同按阅读数），只统计知识文档（上传 DOCUMENT + 在线 ALIDOC，约 6,700 个）。钉钉无企业级排行接口，采用后台并发扫描（并发 3，约 30 分钟），结果缓存 24 小时；扫描期间展示已统计部分，面板显示进度 `统计中 x/y`，文档名可点击跳转钉钉原文 |
| 问答准确率 / 活跃知识占比 / 评测集通过率 / Owner 响应及时率 / 健康度分布 / Owner 贡献榜 | 模拟数据 | 均标注「示例数据」，后续有真实逻辑再替换 |

> **存储总量为什么与钉钉后台（几个 TB）对不上**：遍历只能累加**上传类文件**的 `size`（文档/图片/视频/音频/压缩包等，约 0.8TB）；**钉钉在线文档**（`.adoc`/`.able`/`.axls`/`.amind` 及快捷方式 `.dlink`/`.hlink`，约 260+ 个节点）节点接口返回 `size=0`，且个人钉盘/群文件不在团队知识库（Wiki）遍历范围内。这些只有企业存储接口能覆盖，因此准确的存储总量**必须开通 `Storage.Org.Read` 权限**，开通后无需改代码即自动显示真实值。
>
> **钉钉官方 CLI（dws）兜底**：`tools/dws/dws` 为钉钉开源 CLI（v1.0.61，darwin-arm64，Apache-2.0）。已配置 `dws auth login` 用户扫码授权（杰克科技，refresh token 约 30 天有效，过期后重新扫码即可）。后端 `get_org_storage_used()` 在存储 API 权限不足时自动调用 `dws drive quota apps`（分页汇总 19 个应用用量，TTL 10 分钟缓存），无需依赖应用权限。CLI 路径可用环境变量 `DWS_BIN` 覆盖；服务器/容器部署时需用 `dws auth export/import` 迁移凭证并以 `DWS_DISABLE_KEYCHAIN=1` 运行。

## 项目结构

```
knowledge-governance-expert/
├── docker-compose.app.yml       # 应用容器（kb-api/faq-service/kb-worker）
├── tools/dws/                   # 钉钉官方 CLI（dws），存储总量兜底查询（用户 OAuth 授权）
├── .env / .env.example          # 开发模式 env（含 Dify 配置）
├── .env.docker                  # Docker 全量模式 env
├── dify/                        # 内置 Dify 源码 + docker compose（知识库后端）
│   └── docker/
│       ├── .env                 # Dify 启动配置（INIT_PASSWORD / EXPOSE_NGINX_PORT=8088）
│       ├── docker-compose.yaml  # 完整 Dify 服务栈
│       └── pull-images.sh       # 单镜像重试拉取脚本（国内网络续传）
├── scripts/
│   ├── smoke_test.sh            # 端到端冒烟（覆盖 RAG + FAQ + API Key + 设置）
│   └── seed_admin.py            # 种子 admin 用户
├── services/
│   ├── kb-common/               # 共享：models/clients/rag/auth/config（含 dify_client）
│   ├── kb-api/                  # FastAPI + Celery
│   │   └── app/services/agent/  # LangGraph 智能问答 Agent（workflow/prompts/run）
│   └── faq-service/             # FAQ KB + 精准匹配（FastAPI）
└── web/                         # Vue3 + Element Plus 前端（七大治理模块）
    ├── public/about.html        # 「关于我」产品介绍页（侧边栏左下角新页签打开）
    └── src/views/
        ├── chat/                # 智能问答（Dify 数据集多选 + Agent）
        ├── hiagent/             # HiAgent智能问答（火山 HiAgent WebSDK iframe 嵌入）
        ├── governance/          # 知识治理 7 大模块（含 model.vue 接入配置；治理标准页实时读取钉钉多维表《杰克知识管理规范》，需应用开通 Notable.Base.Read.All 权限）
        └── settings/            # 兼容旧路由的模型配置页（隐藏）
```
