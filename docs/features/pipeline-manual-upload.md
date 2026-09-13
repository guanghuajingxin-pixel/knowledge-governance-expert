# 手动上传适配 Dify 流水线知识库

> 变更单编号：CHG-2026-09-11-02
> 影响范围：kb-api / kb-common / web
> 状态：**✅ 已交付**（2026-09-11）

---

## 1. 目标

1. 前端手动上传 `:limit="5"` 放开到 `:limit="100"`
2. 手动上传/钉钉同步两条路径都能识别 Dify **流水线数据集**（`runtime_mode=rag_pipeline`），自动走 `pipeline/file-upload` + `pipeline/run` 三步接口，不再报 `No subchunk segmentation found in rules`

## 2. 现状问题

| 路径 | 当前实现 | 流水线数据集表现 |
|---|---|---|
| 前端手动上传 | `dify_route.py:upload_dify_document` → `kb_common/clients/dify_client.py:upload_document` → `create-by-file` | ❌ 索引失败 |
| 钉钉单文件同步 | `dify_route.py:sync_dingtalk_file` → 同上 | ❌ 索引失败 |
| 目录同步引擎 | `engine.py` → `sync/dify_sync_client.py:upload_file_via_pipeline` | ✅ 正常 |

流水线三步接口在同步版客户端 `sync/dify_sync_client.py:157-228` 已经封装好，但通用异步版 `kb_common/clients/dify_client.py` 没有对应能力。

## 3. Dify 流水线接口规格（已验证）

**Step 1** — 定位起始节点
```
GET /datasets/{dataset_id}/pipeline/datasource-plugins?is_published=true
→ [{node_id, datasource_type: "local_file", ...}, ...]
挑 datasource_type=local_file 的第一个 node_id
```

**Step 2** — 上传文件到暂存区
```
POST /datasets/pipeline/file-upload
Content-Type: multipart/form-data
Body: file=<binary>
→ {id: <reference>, name, size, ...}
```

**Step 3** — 阻塞式运行流水线
```
POST /datasets/{dataset_id}/pipeline/run
Content-Type: application/json
Body:
{
  "inputs": {},
  "datasource_type": "local_file",
  "datasource_info_list": [{"reference": "<step2.id>", "name": "<文件名>"}],
  "start_node_id": "<step1.node_id>",
  "is_published": true,
  "response_mode": "blocking"
}
→ {batch, documents: [{id, indexing_status, ...}]}
```

## 4. 改造清单

### 4.1 后端

| 文件 | 改动 |
|---|---|
| `services/kb-common/kb_common/clients/dify_client.py` | 新增 4 个方法（异步版）：<br>`list_datasource_nodes(dataset_id)`<br>`local_file_node_id(dataset_id)` — 带 5 分钟内存缓存<br>`upload_pipeline_file(filename, content)`<br>`run_pipeline(dataset_id, start_node_id, reference, name, timeout)`<br>`upload_document_via_pipeline(dataset_id, filename, content, timeout)` — 三步一站式<br>改造 `upload_document()`：先 `get_dataset` 拿 `runtime_mode`，若是 `rag_pipeline` 则调 `upload_document_via_pipeline`，否则走原 `create-by-file` |
| `services/kb-api/app/routes/dify_route.py` | `upload_dify_document` / `sync_dingtalk_file` 无需改动（自动受益于 `upload_document` 内部分流），但需要把超时时间从默认调高到 600 秒 |

### 4.2 前端

| 文件 | 改动 |
|---|---|
| `web/src/views/governance/collection/ManualUpload.vue` | `:limit="5"` → `:limit="100"`<br>`on-exceed` 提示文案改 100<br>`{{ files.length }} / 5 个` → `/ 100 个`<br>`每批 ≤ 5 个` → `每批 ≤ 100 个`<br>上传循环改成**并发 3**（`p-limit` 风格手写）：流水线阻塞模式每个 30s~3min，串行 100 个用户等不起<br>进度条按已完成数计算，保留失败列表 |
| `web/src/api/dify.ts` | `uploadDifyDocument` 的 `timeout: 240000` → `timeout: 600000`（10 分钟） |

## 5. 关键决策（默认值，如需调整告诉我）

| 项 | 默认值 | 理由 |
|---|---|---|
| 前端上传并发数 | **3** | 保守，避免打爆 Dify/MinerU；100 个文档 ≈ 15~100 分钟，用户能接受 |
| 单次上传 timeout | **600s (10min)** | 流水线阻塞模式含解析+分段+索引，比 create-by-file 慢 |
| `local_file_node_id` 缓存 | **5 分钟内存缓存** | 同一 dataset 100 次上传不用查 100 次节点 |
| 钉钉单文件同步 | **一起修** | 同一个 bug，一起改省事 |
| 目录同步引擎 | **不动** | 现有 `sync/dify_sync_client.py` 已经能跑 |

## 6. 落地顺序（3 个 commit）

| # | 提交 | 内容 | 验证 |
|---|---|---|---|
| 1 | `feat(kb-common): dify_client 支持流水线数据集上传` | 5 个新方法 + `upload_document` 分流 + 单元测试 | 手动 curl 或 pytest 上传一个文件到流水线 dataset 能返回 document_id |
| 2 | `feat(kb-api): 手动上传/钉钉同步接口超时提升到 600s` | `dify_route.py` 超时/异常处理 | 现有接口回归 |
| 3 | `feat(web): ManualUpload limit=100 + 并发 3 + timeout 提升` | 前端两个文件 | 上传 6 个文档到流水线 dataset，能看到 3 个并发进度，全部成功 |

## 7. 回滚

- 每个 commit 独立可 revert
- 无 DB 变更、无基础设施变更
- 前端 limit 是纯 UI 参数，改回 5 即可

## 8. 待你确认的问题

1. **前端并发数**：默认 3，你要不要更快（5）或更保守（1，串行）？
2. **钉钉同步路径**：一起修还是先只修手动上传？
3. **变更单**：这份方案 OK 我就按 3 个 commit 顺序动手；有想调整的告诉我

---

## 9. 实施结果（2026-09-11 交付）

用户确认参数：**并发 5、只修钉钉同步（底层 `upload_document` 分流两条路径自动受益）、node_id 缓存 5 分钟、前端单批 ≤ 100**。

### 变更文件

| 文件 | 变更 |
|---|---|
| `services/kb-common/kb_common/clients/dify_client.py` | 新增 `_upload_headers` / `_format_dify_http_error` / `_local_file_node_id`（5min 缓存） / `_upload_via_pipeline`（三步接口） / `_upload_via_create_by_file`；改造 `upload_document` 按 `runtime_mode` 自动分流；client timeout 180s→600s |
| `services/kb-common/tests/test_document_upload.py` | 新增 3 个 pipeline 测试：三步接口命中、node_id 缓存生效、缺失 local_file 节点报错 |
| `web/src/api/dify.ts` | `uploadDifyDocument` timeout 240s→600s |
| `web/src/views/governance/collection/ManualUpload.vue` | `currentFile` 单值 → `activeFiles` 数组；`upload()` 串行 → 共享游标 + 5 个 worker 并发；`:limit="5"` → `:limit="MAX_BATCH"`（100）；文案/进度条/说明卡片全部同步 |

### 未变更文件

- `services/kb-api/app/routes/dify_route.py` — 无需改动，底层 `upload_document` 自动分流，两条路径（`upload_dify_document` / `sync_dingtalk_file`）都受益
- `services/kb-api/app/services/sync/dify_sync_client.py` — 同步版客户端保持不变，目录同步引擎继续走它

### 验证结果

```
kb-common: 22 passed in 0.13s   (19 原有 + 3 新增 pipeline 测试)
kb-api:    14 passed in 0.37s   (sync 引擎回归)
web:       vue-tsc --noEmit     EXIT_CODE=0
```

---

## 10. 手动冒烟测试

### 前置条件

1. Dify 中已有一个 `runtime_mode=rag_pipeline` 的知识库，且流水线中已配置**本地文件**数据源节点并点击过**发布**
2. 平台"系统配置 → Dify 链接配置"里的 base_url / api_key 能访问该知识库

### 测试步骤

**A. 单文件冒烟（验证 pipeline 三步接口通）**

```bash
# 1. 启动 kb-api
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000

# 2. 用 curl 上传一个 txt 到流水线数据集
curl -X POST http://localhost:8000/api/v1/dify/datasets/<PIPELINE_DATASET_ID>/documents \
  -H "Authorization: Bearer <你的 JWT>" \
  -F "file=@/tmp/hello.txt"

# 期望返回：{"document_id": "...", "name": "hello.txt", "batch": "..."}
# kb-api 日志应能看到 GET /pipeline/datasource-plugins、POST /pipeline/file-upload、POST /pipeline/run 三次调用
```

**B. 前端手动上传（验证并发 5 + limit 100）**

1. 打开 `web` → 知识集成 → 采集 → 上传本地文档
2. 选择流水线数据集，拖入 6~10 个文档
3. 点击"开始上传"
4. 观察：
   - 进度条上方文案应显示"已完成 X / Y，正在处理 N 个：..."（N 最大为 5）
   - 浏览器 Network 面板应看到最多 5 个 `POST /dify/datasets/.../documents` 并发
   - 全部完成后弹出成功消息，Dify 控制台该数据集文档数增加

**C. 钉钉同步路径（验证 sync_dingtalk_file 也走 pipeline）**

1. 前端 → 知识集成 → 采集 → 钉钉同步
2. 选择一个钉钉节点，目标选流水线数据集，点击同步
3. 观察 kb-api 日志：应看到走 pipeline/run 而不是 create-by-file

### 失败排查

| 现象 | 排查 |
|---|---|
| `Dify 知识流水线未配置本地文件数据源节点` | 到 Dify 流水线编辑器加"本地文件"节点并**发布**（草稿状态不算） |
| `No subchunk segmentation found in rules` | 说明还是走了 create-by-file，检查 `get_dataset` 返回的 `runtime_mode` 字段名是否与代码判断一致 |
| 前端超时 | `web/src/api/dify.ts` timeout 已是 600000，若仍超时说明 Dify 流水线单文档处理 >10 分钟，需要调优 Dify 侧 |
| 缓存导致节点 ID 过期 | 5 分钟内 Dify 侧修改了流水线，重启 kb-api 或等 5 分钟缓存过期 |

---

## 11. 后续可选优化（未实施）

1. **进度上报**：`pipeline/run` 阻塞模式前端只能等最终结果，可以在后端加 SSE 推送分段进度
2. **批量接口**：Dify `datasource_info_list` 支持多个 reference，理论上可以一次 run 处理多个文件，减少 API 调用次数
3. **失败重试队列**：见 `rocketmq-sync-queue.md`（暂停中）

---

## 12. 补充修复（2026-09-11 第二轮）

首版实现按"sync 客户端已有的返回结构"直接抄了假设：`{batch, documents: [{id}]}` 在响应顶层。**这是错的**。用户实测反馈"还是不正确"后，核对 Dify 官方文档 + `dify/api/core/app/entities/task_entities.py:892` 的 `WorkflowAppBlockingResponse` 源码，确认 `pipeline/run` 阻塞模式的真实响应结构是：

```json
{
  "task_id": "...",
  "workflow_run_id": "...",
  "data": {
    "id": "...",
    "workflow_id": "...",
    "status": "succeeded",
    "outputs": {
      "dataset_id": "...",
      "dataset_name": "...",
      "batch": "20250306150245647595",
      "document_id": "a8e0e5b5-...",
      "document_name": "guide.txt",
      "display_status": "indexing",
      "created_at": 1741267200
    },
    "error": null,
    "elapsed_time": 1.5,
    "total_tokens": 0,
    "total_steps": 3
  }
}
```

`document_id` 和 `batch` **藏在 `data.outputs`**（由 `knowledge_index` 节点写入，schema 见 `dify/api/core/workflow/nodes/knowledge_index/protocols.py:8-16` 的 `IndexingResultDict`），响应顶层根本没有 `documents[]`。

### 修复的文件

| 文件 | 变更 |
|---|---|
| `services/kb-common/kb_common/clients/dify_client.py` | `_upload_via_pipeline` 解析 `data.outputs.document_id` / `data.outputs.batch`；校验 `data.status=='succeeded'`，否则带上 `workflow_run_id` + `data.error` 抛错；返回结构归一化为 `{document:{id,name,indexing_status,data_source_type}, batch, runtime_mode, workflow_run_id}` |
| `services/kb-api/app/services/sync/dify_sync_client.py` | `upload_file_via_pipeline` 同款修复（这个 bug 原来就有，只是目录同步遇到流水线数据集时会静默拿到空 document_id） |
| `services/kb-common/tests/test_document_upload.py` | 前两个 pipeline 测试的 mock 响应改成真实的 `WorkflowAppBlockingResponse` 结构；新增 2 个失败路径测试：`data.status=failed` 抛错、`outputs` 缺 `document_id` 抛错 |

### 关键教训

- 复用别人已封装的代码前，**必须核对该代码是否真的跑通过目标场景**。sync 版 `upload_file_via_pipeline` 存在很久，但目录同步引擎可能一直没跑过流水线数据集，所以 bug 没暴露
- Dify 的 pipeline/run 响应遵循 `WorkflowAppBlockingResponse`，不是 `create-by-file` 的 `{document, batch}` 结构；两个接口虽然都能"上传文档"，但响应契约完全不同
- 遇到"接口调用成功但拿不到 ID"的现象，第一反应应该是**打印真实响应体**，而不是猜结构

### 验证结果

```
kb-common: 24 passed in 0.13s   (19 原有 + 5 pipeline 测试)
kb-api:    14 passed in 0.28s   (sync 引擎回归)
```

### 冒烟测试补充

在原来的三步测试基础上，**必须验证前端能拿到非空的 document_id**：

```bash
curl -X POST http://localhost:8000/api/v1/dify/datasets/<PIPELINE_DATASET_ID>/documents \
  -H "Authorization: Bearer <JWT>" \
  -F "file=@/tmp/hello.txt" | jq

# 期望：
# {
#   "document_id": "a8e0e5b5-...",   ← 非空 UUID
#   "name": "hello.txt",
#   "batch": "20250306150245647595"  ← 非空批次号
# }
```

如果 `document_id` 为空，说明 Dify 流水线末尾**没有『知识索引』节点**或该节点未发布，此时后端会抛出明确的中文错误提示。

---

## 13. 第三轮修复（2026-09-11 真实 API 实测）

前两轮修复都**基于 Dify 源码/官方文档推断**，结果都错了。用户反馈"还是报错"后，写了独立测试脚本 `/tmp/test_dify_pipeline.py` 直接打本地 Dify 1.16.1（`http://127.0.0.1:8088/v1`，目标数据集「供应链知识库」`244d2c51-5501-47b6-aed6-c6b464bd160e`，`runtime_mode=rag_pipeline`），才看到真实行为。

### 实测发现的两个 bug

**Bug 1：`inputs` 不能传空对象**

```json
// 请求
{"inputs": {}, "datasource_type": "local_file", ...}

// Dify 响应 HTTP 500
{"code": "pipeline_run_error", "message": "max_chunk_length is required in input form", "status": 500}
```

该流水线在 Dify 编辑器里定义了 `max_chunk_length` 输入变量（分段节点的标准参数），调用时必须传值。修复：默认传 `{"max_chunk_length": 1024}`（Dify 标准分段长度）。

**Bug 2：真实响应结构跟官方文档/源码完全不一样**

官方文档 + `dify/api/core/app/entities/task_entities.py:892` 的 `WorkflowAppBlockingResponse` 都暗示响应是：
```json
{"task_id": "...", "workflow_run_id": "...", "data": {"status": "succeeded", "outputs": {...}}}
```

**实际 HTTP 200 响应**（Dify 1.16.1）：
```json
{
  "batch": "20260911160345142668",
  "dataset": {"id": "...", "name": "供应链知识库", "chunk_structure": "text_model"},
  "documents": [{
    "id": "17407947-ac13-4d89-9d2b-0416f9566db3",
    "name": "杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf",
    "indexing_status": "waiting",
    "data_source_type": "local_file",
    "position": 3,
    "error": null,
    "enabled": true
  }]
}
```

`document_id` 在 `documents[0].id`，`batch` 在顶层 `batch`，**不在** `data.outputs`。第二轮"修复"改错了方向。

### 修复的文件

| 文件 | 变更 |
|---|---|
| `services/kb-common/kb_common/clients/dify_client.py` | `_upload_via_pipeline`：`inputs` 传 `{"max_chunk_length": 1024}`；响应解析改成 `documents[0].id` + 顶层 `batch`；保留 `data.outputs` 兜底路径以兼容未来 Dify 版本切换到官方文档结构 |
| `services/kb-api/app/services/sync/dify_sync_client.py` | `run_pipeline` 同样传 `max_chunk_length`；`upload_file_via_pipeline` 同样改响应解析 |
| `services/kb-common/tests/test_document_upload.py` | 3 个 pipeline 测试的 mock 响应改成真实的 `{batch, dataset, documents[]}` 结构；`test_pipeline_run_status_failed_raises` 改成测 HTTP 500 + `pipeline_run_error` 真实错误 |

### 端到端验证输出

```
📄 文件: 杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf
   大小: 266976 bytes
   MIME: application/pdf

Step 1: start_node_id = 1752479895761
Step 2: reference = be20de1a-22b2-4bb7-8eb5-029d21475c68
        Dify 侧存储的 name = '杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf'
        Dify 侧识别的 extension = 'pdf'
        Dify 侧识别的 mime_type = 'application/pdf'
Step 3: HTTP 200

🎯 最终结果
batch           : 20260911160345142668
document_id     : 17407947-ac13-4d89-9d2b-0416f9566db3
document_name   : '杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf'
indexing_status : waiting
✅ Dify 返回的 document_name 与原始 filename 完全一致（扩展名保留）
```

### 关键教训（必须记住）

1. **Dify 官方文档 + 源码都可能跟实际运行行为不一致**。`WorkflowAppBlockingResponse` 是 workflow 应用的响应 schema，rag_pipeline 实际复用了 `create-by-file` 风格的 `{batch, dataset, documents[]}` 响应
2. **遇到"接口调用失败"必须先用独立脚本打真实 API**，看完整请求/响应，而不是靠读源码猜
3. **`inputs` 是流水线级别的输入变量**，不是数据源节点的 `user_input_variables`；不同流水线可能需要不同的 inputs，默认值 `max_chunk_length=1024` 只覆盖最常见场景，复杂流水线可能需要上层配置项支持自定义 inputs
4. **httpx 三元组显式传 mimetype 是对的**（第二轮修复没白做），中文文件名 + `.pptx`/`.pdf` 场景下 Dify 侧 `extension` 和 `mime_type` 都正确识别

### 验证结果

```
kb-common: 24 passed in 0.11s
kb-api:    14 passed in 0.31s
端到端:    /tmp/test_dify_pipeline.py HTTP 200，document_name 与原始 filename 完全一致
```

---

## 14. 流水线分段参数可配置（2026-09-11 第四轮）

### 背景

用户在 Dify 控制台手动上传时需要填「分段设置」表单（Parent Mode / Child Delimiter / Maximum Child Length 等）。直连 Dify 数据库读出 `workflows.rag_pipeline_variables` 后发现：**不同流水线的 input form 变量完全不同**：

| 流水线 | 变量 |
|---|---|
| 供应链知识库（自动分段） | `delimiter`、`max_chunk_length`(必填无默认)、`chunk_overlap`、`replace_consecutive_spaces`、`delete_urls_email` |
| 截图那个（parent/child 分段） | `parent_mode`、`parent_dilmiter`(Dify 拼错)、`parent_length`、`child_delimiter`、`child_length`、`clean_1`、`clean_2` |

硬编码 `{"max_chunk_length": 1024}` 换流水线就失效。且 Dify Service API **不暴露**变量 schema（只有 4 个路由）。

本地 Dify 的 `patches/base_app_generator.py` 补丁只救"必填但**有**默认值"的变量；`max_chunk_length` 这类**无默认值**的必填变量传 `{}` 仍报 500。前端配置正好补上这个缺口，与补丁兼容（传了 inputs 用传的值，没传补丁填默认值）。

### 架构

```
dify_db_url (.env, 只读)
   ↓ sqlalchemy 直连 Dify postgres
dify_pipeline_vars.fetch_pipeline_variables(dataset_id)
   ↓ 查询链 datasets.pipeline_id → pipelines.workflow_id → workflows.rag_pipeline_variables
GET /api/v1/sync/pipeline-variables?dataset_id=xxx
   ↓ {configured, variables: [{variable,label,type,required,default_value,options,unit,tooltips}]}
前端自动生成表单（select→el-select / number→el-input-number / checkbox→el-switch / 其他→el-input）
   ↓ 未配置 dify_db_url 时降级为 JSON textarea
sync_sources.pipeline_inputs (Text 存 JSON)  ←  每个同步源独立配置
   ↓ engine.py 同步时解析传入
dify.upload_file_via_pipeline(..., inputs=pipeline_inputs)
```

### 变更文件

| 层 | 文件 | 变更 |
|---|---|---|
| 配置 | `kb_common/config.py` | + `dify_db_url`（可选，留空降级） |
| 配置 | `.env` | + `DIFY_DB_URL=postgresql+psycopg://postgres:***@127.0.0.1:5433/dify` |
| 部署 | `dify/docker/docker-compose.yaml` | db_postgres + `ports: 5433:5432`（避开 dev-postgres 的 5432） |
| DB | `kb_common/models.py` + `alembic/versions/0021_...py` | sync_sources + `pipeline_inputs` Text 列（已 upgrade head） |
| 后端 | `app/services/sync/dify_pipeline_vars.py` | **新建**：直连 Dify DB 只读查询 schema，引擎缓存 + pool_pre_ping |
| 后端 | `app/routes/sync_route.py` | + `GET /pipeline-variables`；create/update source 序列化 pipeline_inputs |
| 后端 | `app/schemas.py` | SyncSourceBase/Update/Out + pipeline_inputs（Out 带 validator 把 Text 转 dict） |
| 后端 | `dify_sync_client.py` / `kb_common dify_client.py` | pipeline 方法 + `inputs` 参数（未传回退 `{"max_chunk_length":1024}`） |
| 后端 | `engine.py` | 同步时解析 `source.pipeline_inputs` 传入 + INFO 日志 |
| 后端 | `dify_route.py` | 手动上传 + multipart 字段 `pipeline_inputs` |
| 前端 | `types/sync.ts` / `api/sync.ts` / `api/dify.ts` | + PipelineVariable 类型、listPipelineVariables、uploadDifyDocument 第三参 |
| 前端 | `SourceFormDialog.vue` | 折叠区「流水线分段参数」：schema 自动表单 / JSON 兜底 + 必填校验 |
| 前端 | `ManualUpload.vue` | 同款折叠区；上传时校验必填并随每个文件传 pipeline_inputs |

### 端到端验证

```bash
GET /api/v1/sync/pipeline-variables?dataset_id=244d2c51-...
→ {"configured": true, "variables": [5 个变量完整 schema]}

POST /api/v1/dify/datasets/244d2c51-.../documents
  -F file=@杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf
  -F pipeline_inputs={"max_chunk_length": 1024, "delimiter": "\n\n"}
→ {"document_id": "b77e93c3-34bb-4082-8421-f1db0f02c127",
   "name": "杰克_产品质量山头项目激励方案_供应链军团_方案_20260804_V1.0.pdf",
   "batch": "20260911164441228742"}
```

```
kb-common: 24 passed
kb-api:    14 passed
web:       vue-tsc --noEmit EXIT=0
```

### 使用说明

1. **同步源配置页**：选完 Dify 知识库后自动拉取该流水线的分段参数表单（带 label/类型/默认值/单位/tooltip），必填项标红星；保存后每个同步源独立生效
2. **手动上传页**：选完目标知识库后同款表单出现；未配置 `dify_db_url` 时显示 JSON 编辑器兜底
3. **不配置也能跑**：流水线变量全部有默认值时，传 `{}` 靠 Dify 本地补丁回退默认值；只有存在"必填且无默认值"变量时才必须配置

---

## 15. 目录级批量同步到普通知识库（2026-09-11 第五轮）

### 根因（与流水线无关）

目录同步源同步到**普通知识库**整批失败（run 47：total=4 failed=4，错误 `upload file: invalid_param` 空 message）。逐层复现：

1. curl create-by-file 传 `doc_form=text_model` → `doc_form is different from the dataset doc_form`（数据集实际是 `hierarchical_model`，sync 客户端读对了，是我 curl 传错）
2. curl 传正确 `doc_form=hierarchical_model` + **pdf** → 成功
3. curl 传正确 doc_form + **pptx** → `invalid_param` 空 message
4. Dify api 日志：`UnsupportedFileTypeError`

**Dify 的格式支持取决于 `ETL_TYPE`**（`dify/api/constants/__init__.py:56-66`）：
- 内置 ETL（默认）：`txt/md/mdx/pdf/html/htm/xlsx/xls/docx/csv/vtt/properties` —— **无 pptx/ppt/doc**
- `ETL_TYPE=Unstructured` 才支持 pptx/doc/eml/msg/xml/epub

"指定文档同步"（collection.vue）之所以能通：它的 `isSyncable` 白名单与内置 ETL **完全对齐**，pptx 在前端就标"暂不支持"禁勾。**目录同步源的 engine 没有这层过滤**，下载 pptx 硬发被 Dify 拒，整批 failed。

### 修复

| 文件 | 变更 |
|---|---|
| `kb_common/clients/document_upload.py` | + `DIFY_BUILTIN_ETL_EXTENSIONS` 常量（与 Dify `_DEFAULT_DOCUMENT_EXTENSION_BASE` 对齐） |
| `app/services/sync/engine.py` | 同步循环在**下载前**按白名单过滤；在线文档（adoc/axls/able/mind/ALIDOC，导出后为 docx/xlsx/pdf）豁免；skip 记 INFO 日志（含扩展名与 Unstructured 提示）并清掉该节点历史 SyncFailure |
| `app/routes/sync_route.py` | `preview_source` 同步标注：不支持格式的文档 action=跳过 + note 说明原因，预演清单与引擎行为一致 |
| `tests/test_sync.py` | 原 fixture 的 `课件.pptx` 改 `课件.pdf`（否则被白名单 skip 破坏索引失败断言）；新增 `test_unsupported_extension_skipped_without_upload` 验证 pptx 不触达上传、mapping 只建 pdf、历史 failure 被清 |

### 验证

```
run 48（源 11，目录全 pptx → 普通库）: status=success total=4 created=0 failed=0，failures 清零
run 49（源 2，pptx+adoc → 普通库）:  status=success total=2 updated=1 failed=0
  INFO 跳过（Dify 内置解析不支持 .pptx 格式，需 Dify 配置 Unstructured 或转存为支持格式）: 杰克_智能体RAG方案...pptx
  INFO 更新 Dify 文档: 我让AI画了个图.adoc
  INFO 索引状态: 我让AI画了个图.adoc -> completed
kb-api: 15 passed
```

## 16. 切换 Unstructured ETL + 白名单随 ETL 类型联动（2026-09-12，两项遗留的实施）

用户确认两项遗留都按建议实施：① 给 Dify 配 Unstructured 让 pptx 可同步；② ManualUpload 的格式限制与 Dify 实际能力对齐。

### 基础设施

| 项 | 值 |
|---|---|
| Unstructured 容器 | `docker run -d --name dev-unstructured -p 8013:8000 quay.io/unstructured-io/unstructured-api:latest`（docker.io 的 daocloud 镜像源 403，改 quay.io） |
| 网络 | `docker network connect docker_default dev-unstructured`，Dify 容器内经服务名访问 |
| Dify `.env` | `ETL_TYPE=Unstructured` + `UNSTRUCTURED_API_URL=http://dev-unstructured:8000`（constants 里精确匹配大写 `"Unstructured"`） |
| 重启 | `docker compose up -d api worker`（ETL_TYPE 启动时读） |

### 代码

| 文件 | 变更 |
|---|---|
| `kb_common/clients/document_upload.py` | + `DIFY_UNSTRUCTURED_ETL_EXTENSIONS`（19 种，比内置多 doc/pptx/eml/msg/xml/epub）+ `supported_dify_extensions(etl_type)` 大小写不敏感切换 |
| `kb_common/config.py` | + `dify_etl_type: str = "dify"`（镜像 Dify 侧 ETL_TYPE；Service API 不暴露该配置） |
| `engine.py` / `sync_route.py` preview | 白名单改 `supported_dify_extensions(s.dify_etl_type)`；skip 日志/note 带当前 ETL 类型 |
| `dify_route.py` | + `GET /api/v1/dify/supported-extensions` 返回 `{etl_type, extensions[]}`（纯配置读） |
| `api/dify.ts` + `ManualUpload.vue` | `extensions` 改 ref（内置 13 种兜底），挂载时拉真实白名单；`accept` 改 computed；校验信息带 ETL 类型；说明卡片动态展示 ETL 与格式列表 |
| `.env`（kb-api） | + `DIFY_ETL_TYPE=Unstructured` |
| `tests/test_sync.py` | + `make_fake_settings` helper；新增 `test_pptx_synced_when_dify_runs_unstructured_etl`；skip 测试固定 etl=dify 不依赖环境 |

### 验证结果

```
curl http://127.0.0.1:8013/healthcheck → {"healthcheck":"HEALTHCHECK STATUS: EVERYTHING OK!"}
curl pptx(267KB) create-by-file → ✅ document_id=f47ddb8d-... batch=20260911175030382253
   （内置 ETL 下同一文件报 UnsupportedFileTypeError → 空 message invalid_param）
GET /api/v1/dify/supported-extensions → etl_type=Unstructured, 19 种格式（含 pptx/doc/eml/msg/xml/epub）
run 52（源11，2 个 pdf → 普通库）: success total=2 updated=2 failed=0
run 53（源2，adoc + 117MB pptx）: partial total=2 updated=1 failed=1
   pptx 不再被白名单 skip，走到上传环节后因「单个文件不得超过 15 MB」单个失败；
   同批 adoc 正常更新 → 单个失败不拖累整批，status=partial 正确反映
kb-common 24 passed · kb-api 16 passed · vue-tsc EXIT=0
```

preview 清单里 pptx 的 action 从「跳过」变为「更新/新增」，与引擎行为一致。

### 运维注意

- **两侧 ETL 配置必须同步改**：Dify `.env` 的 `ETL_TYPE` 与 kb-api `.env` 的 `DIFY_ETL_TYPE`。只改一边会出现"白名单放行但 Dify 拒收"或"Dify 支持但白名单拦掉"
- Unstructured 服务不可达时，Dify 在**解析阶段**失败（不是上传接口 400），排查看 dify api 日志的 unstructured 连接错误
- 切换 ETL 不影响已索引文档；新上传/重新同步的文档走新解析器

### 已决策：>15MB 文件维持现状（2026-09-12 用户选定方案 3）

Dify `UPLOAD_FILE_SIZE_LIMIT` 默认 15MB，`prepare_document` 同限。117MB 的 pptx 任何 ETL 都传不上去。
用户选定**维持现状**：超限文件单个失败 + 明确错误提示，不拖累整批。

- 失败表现：engine 下载后 `prepare_document` 抛 `单个文件不得超过 15 MB，请压缩或拆分后上传。`，记入 SyncFailure，Monitor「失败」列表可见；同批其他文件正常同步，run status=partial
- 不选 MinerU 兜底（>15MB → 解析 Markdown → create-by-text）：需 `MINERU_API_KEY`，当前未配置；将来配了 key 再补此兜底
- 不选调大 Dify `UPLOAD_FILE_SIZE_LIMIT`：100MB+ 解析的内存/耗时风险大
