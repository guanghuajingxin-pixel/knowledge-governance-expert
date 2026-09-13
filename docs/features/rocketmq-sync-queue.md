# 知识集成同步队列改造方案（RocketMQ）

> 变更单编号：CHG-2026-09-11-01
> 影响范围：kb-api / kb-worker / web / 基础设施 / 部署
> 状态：**⏸ 暂停**（2026-09-11 用户决定先做流水线上传适配，队列改造后续再启动）
> 后续方案见：`docs/features/pipeline-manual-upload.md`

---

## 1. 目标

1. 前端手动上传放开到 100 个文件/批
2. 后端"知识集成 → 同步推送"引入 RocketMQ 队列，双阈值触发：
   - **阈值 A**：单源本次要推的文档数 > 100 → 拆分文档级消息进队列
   - **阈值 B**：全局并发运行任务数 > 100 → 整个 run 排队等待

## 2. 架构总览

```
┌─────────────────┐  HTTP  ┌──────────────┐  produce  ┌──────────────────┐
│  web (Vue)      │───────▶│  kb-api      │──────────▶│  RocketMQ        │
│  ManualUpload   │        │  sync_route  │           │  namesrv + broker│
└─────────────────┘        └──────┬───────┘           └────────┬─────────┘
                                  │ ≤100 走线程池              │ consume
                                  ▼                            ▼
                           ┌──────────────┐           ┌──────────────────┐
                           │ _executor    │           │ sync_consumer    │
                           │ (原有串行)   │           │ (新增独立进程)   │
                           └──────┬───────┘           └────────┬─────────┘
                                  │                            │
                                  └──────────────┬─────────────┘
                                                 ▼
                                          ┌──────────────┐
                                          │  Dify        │
                                          └──────────────┘
```

## 3. 消息模型

| 项 | 值 |
|---|---|
| Topic（文档级） | `kb-sync-document` |
| Topic（run 级） | `kb-sync-run` |
| Tag | `create` / `update` / `delete` / `run` |
| Consumer Group | `kb-sync-consumer` |
| 消息 Key | `{source_id}:{node_id}:{run_id}` — 用于幂等 + 消息轨迹查询 |
| 消息 Body | JSON，见下 |

**文档级消息 Body**：
```json
{
  "run_id": 123,
  "source_id": 1,
  "node_id": "xxx",
  "name": "产品手册.pdf",
  "action": "create",
  "attempt": 1,
  "enqueued_at": "2026-09-11T10:00:00Z"
}
```

**run 级消息 Body**：
```json
{
  "source_id": 1,
  "trigger": "manual",
  "enqueued_at": "2026-09-11T10:00:00Z"
}
```

## 4. 决策逻辑（在 `sync_route.py` 触发点）

```python
def dispatch_sync(source_id, trigger):
    if not settings.SYNC_QUEUE_ENABLED:
        return _executor.submit(run_sync_direct, source_id, trigger)  # 回滚路径

    pending_docs = count_pending_documents(source_id)
    running_runs = count_running_runs()

    # 阈值 B：全局并发过高，整个 run 排队
    if running_runs >= settings.SYNC_QUEUE_THRESHOLD_RUNS:
        return enqueue_run_message(source_id, trigger)

    # 阈值 A：文档数超阈值，拆分文档级消息
    if pending_docs > settings.SYNC_QUEUE_THRESHOLD_DOCUMENTS:
        return enqueue_document_messages(source_id, trigger)

    # 默认：走原有串行路径
    return _executor.submit(run_sync_direct, source_id, trigger)
```

## 5. 部署改动

### 5.1 基础设施 compose（`~/Documents/03_Resource/开发环境/docker-compose.yml`）

新增：
```yaml
  rocketmq-namesrv:
    image: apache/rocketmq:4.9.7
    container_name: dev-rocketmq-namesrv
    command: sh mqnamesrv
    ports:
      - "${ROCKETMQ_NAMESRV_PORT:-9876}:9876"
    environment:
      JAVA_OPT_EXT: "-Xms512m -Xmx512m"
    networks: [dev-network]

  rocketmq-broker:
    image: apache/rocketmq:4.9.7
    container_name: dev-rocketmq-broker
    depends_on: [rocketmq-namesrv]
    command: sh mqbroker -n rocketmq-namesrv:9876 -c /home/rocketmq/conf/broker.conf
    environment:
      JAVA_OPT_EXT: "-Xms1g -Xmx1g"
      NAMESRV_ADDR: rocketmq-namesrv:9876
    ports:
      - "${ROCKETMQ_BROKER_PORT:-10911}:10911"
      - "10909:10909"
    volumes:
      - rocketmq-store:/home/rocketmq/store
      - ./rocketmq/broker.conf:/home/rocketmq/conf/broker.conf
    networks: [dev-network]

  rocketmq-dashboard:   # 可选，方便观察队列
    image: apacherocketmq/rocketmq-dashboard:latest
    container_name: dev-rocketmq-dashboard
    depends_on: [rocketmq-namesrv]
    environment:
      JAVA_OPTS: "-Drocketmq.namesrv.addr=rocketmq-namesrv:9876"
    ports:
      - "${ROCKETMQ_DASHBOARD_PORT:-8180}:8080"
    networks: [dev-network]

volumes:
  rocketmq-store:
    name: dev-rocketmq-store
```

**新增 `~/Documents/03_Resource/开发环境/rocketmq/broker.conf`**：
```
brokerClusterName=DefaultCluster
brokerName=broker-a
brokerId=0
deleteWhen=04
fileReservedTime=48
brokerRole=ASYNC_MASTER
flushDiskType=ASYNC_FLUSH
brokerIP1=host.docker.internal   # Mac 本机开发；内网服务器改成 10.10.166.2
autoCreateTopicEnable=true
autoCreateSubscriptionGroup=true
```

### 5.2 应用 compose（`docker-compose.app.yml`）

新增 `sync-consumer` 服务：
```yaml
  sync-consumer:
    build: ./services/kb-api
    command: uv run python -m app.sync_consumer
    environment:
      ROCKETMQ_NAMESRV: rocketmq-namesrv:9876
      # ... 复用 kb-api 的环境变量
    depends_on: [rocketmq-namesrv, rocketmq-broker, postgres, redis]
    networks: [dev-network]
    restart: unless-stopped
```

### 5.3 内网服务器（10.10.166.2）

`deploy/intranet/` 同步新增 RocketMQ 容器 + broker.conf（`brokerIP1=10.10.166.2`）。

## 6. 数据库改动

新增 `sync_queue_message` 表（前端可视化 + 死信跟踪）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| run_id | INT FK sync_runs.id | 关联运行记录 |
| source_id | INT FK sync_sources.id | |
| node_id | VARCHAR(128) | 文档节点 ID |
| msg_key | VARCHAR(255) UNIQUE | RocketMQ 消息 Key，幂等用 |
| action | VARCHAR(16) | create/update/delete/run |
| status | VARCHAR(16) | pending/processing/success/failed/dead |
| attempt | INT DEFAULT 0 | 消费次数 |
| error | TEXT | 最后一次错误 |
| created_at / updated_at | TIMESTAMP | |

Alembic 迁移：`alembic/versions/00XX_add_sync_queue_message.py`

## 7. 代码改动清单

### 后端（新增/修改 8 个文件）

| 文件 | 改动 |
|---|---|
| `services/kb-common/kb_common/models.py` | + `SyncQueueMessage` ORM |
| `services/kb-common/kb_common/config.py` | + RocketMQ 相关配置项 |
| `services/kb-api/pyproject.toml` | + `rocketmq-client-python==2.0.0` |
| `services/kb-api/app/services/sync/rocketmq_client.py` | **新建**：producer/consumer 封装 |
| `services/kb-api/app/services/sync/engine.py` | 拆分：`dispatch_sync` / `run_sync_direct` / `process_document_message` |
| `services/kb-api/app/services/sync/runtime.py` | 队列决策接入 |
| `services/kb-api/app/routes/sync_route.py` | 触发同步走 dispatcher，新增队列查询接口 |
| `services/kb-api/app/sync_consumer.py` | **新建**：消费者进程入口 |
| `alembic/versions/00XX_add_sync_queue_message.py` | **新建**：迁移 |

### 前端（修改 3 个文件）

| 文件 | 改动 |
|---|---|
| `web/src/views/governance/collection/ManualUpload.vue` | `:limit="5"` → `:limit="100"`，文案同步；提交改走 `POST /api/v1/sync/manual-upload`（新接口，服务端投递队列） |
| `web/src/api/sync.ts` | + `uploadManualBatch` / `listQueue` / `getQueueStats` |
| `web/src/views/governance/collection/Monitor.vue` | 新增"队列中"tab，展示 `sync_queue_message` 状态 |

### 部署脚本

| 文件 | 改动 |
|---|---|
| `~/Documents/03_Resource/开发环境/docker-compose.yml` | + RocketMQ 三容器 |
| `~/Documents/03_Resource/开发环境/.env` | + RocketMQ 端口配置 |
| `docker-compose.app.yml` | + sync-consumer 服务 |
| `deploy/intranet/*` | 同步 |
| `README.md` | 部署章节新增 RocketMQ |
| `AGENTS.md` | Build & Run 章节新增 sync-consumer 启动命令 |

## 8. 配置项（`.env`）

```env
# RocketMQ
ROCKETMQ_NAMESRV=rocketmq-namesrv:9876
ROCKETMQ_NAMESRV_PORT=9876
ROCKETMQ_BROKER_PORT=10911
ROCKETMQ_DASHBOARD_PORT=8180

# 同步队列
SYNC_QUEUE_ENABLED=true                       # feature flag，false 则完全走原路径
SYNC_QUEUE_TOPIC_DOCUMENT=kb-sync-document
SYNC_QUEUE_TOPIC_RUN=kb-sync-run
SYNC_QUEUE_GROUP=kb-sync-consumer
SYNC_QUEUE_THRESHOLD_DOCUMENTS=100            # 阈值 A
SYNC_QUEUE_THRESHOLD_RUNS=100                 # 阈值 B
SYNC_QUEUE_CONSUMER_CONCURRENCY=8             # 消费者线程数
SYNC_QUEUE_MAX_RETRY=3                        # 本地重试次数，超出后进 RocketMQ 重试队列
```

## 9. 幂等 / 重试 / 死信

- **幂等**：消费前查 `sync_document_mapping.status='synced' AND last_synced_at >= run.started_at`，命中则直接 ACK
- **消息 Key**：`{source_id}:{node_id}:{run_id}`，RocketMQ 侧天然去重（相同 Key 5 分钟内不重投）
- **消费失败**：本地重试 3 次 → 抛异常触发 RocketMQ 重试队列（默认 16 次，间隔递增）→ 达到最大次数进死信 Topic `%DLQ%kb-sync-consumer`
- **死信告警**：`sync_consumer` 同时监听死信 Topic，写入 `sync_queue_message.status='dead'`，前端 Monitor 页面红标显示

## 10. 落地顺序（5 个 commit）

| # | 提交 | 内容 | 验证 |
|---|---|---|---|
| 1 | `feat(infra): 加入 RocketMQ namesrv/broker/dashboard` | 基础设施 compose + broker.conf + .env | `docker compose up`，dashboard 能访问 |
| 2 | `feat(db): 新增 sync_queue_message 表` | ORM 模型 + alembic 迁移 | `alembic upgrade head` 成功，表能建 |
| 3 | `feat(sync): 封装 RocketMQ producer/consumer` | rocketmq_client.py + 单元测试 | 本地能投递并消费一条测试消息 |
| 4 | `feat(sync): engine 拆分 + sync_consumer 进程` | engine.py / runtime.py / sync_route.py 改造，新消费者入口 | 触发一个 >100 文档的源，看消息进队列并被消费 |
| 5 | `feat(web): ManualUpload 100 + 走队列 + Monitor 队列 tab` | 前端三个文件 | 手动上传 100 个文件不卡前端，Monitor 能看到队列进度 |

**每个 commit 独立可回滚**，前 4 个不影响前端行为（feature flag 默认 false，灰度打开）。

## 11. 回滚方案

| 场景 | 回滚动作 |
|---|---|
| RocketMQ 集群故障 | `SYNC_QUEUE_ENABLED=false` → 立即回退到原线程池路径，无需回滚代码 |
| 消费逻辑 bug | 停 `sync-consumer` 容器，堆积消息不丢；修好后再启 |
| DB 迁移问题 | `alembic downgrade -1` 删表 |
| 全量回滚 | revert 5 个 commit，`docker compose down rocketmq-*` |

## 12. 已知风险

1. **rocketmq-client-python 依赖 librocketmq C 库**
   - Mac M1/M2 需要 `brew install librocketmq` 或从源码编译，可能踩坑
   - **备选**：改用 `rocketmq-python` 5.x gRPC 客户端（但要求 broker 5.x，需升级镜像）
   - **建议**：先用 4.9.7 + `rocketmq-client-python==2.0.0`，本地 Mac 编译失败则回退到 5.x 方案

2. **前端手动上传路径改造涉及行为变更**
   - 现在前端直接调 Dify 上传（绕过 kb-api），改队列后必须经过 kb-api 中转
   - 需要新增 `POST /api/v1/sync/manual-upload` 接口，接收 multipart 文件流
   - 100 个文件 × 15MB = 1.5GB 单次上传，需要调 nginx `client_max_body_size` 或前端拆分请求

3. **消息重复投递**
   - RocketMQ 至少一次语义，业务侧必须幂等（已通过 mapping.status 检查覆盖）

4. **Broker 存储**
   - `rocketmq-store` volume 默认预留 20GB，需要监控磁盘占用

5. **内网服务器 CPU 架构**
   - 10.10.166.2 是 x86-64-v1 老 CPU，`apache/rocketmq:4.9.7` 官方镜像基于 OpenJDK 8，兼容性 OK；但需要验证 colima/kvm 内存足够（broker 至少 1GB）

## 13. 待你确认的问题

1. **RocketMQ 版本**：用 4.9.7 + `rocketmq-client-python`（Python 客户端稳定），还是 5.x + `rocketmq-python`（新架构，gRPC）？我倾向 **4.9.7**，社区文档多，Python 客户端成熟。
2. **Dashboard**：是否部署 `rocketmq-dashboard`（8180 端口）？我倾向 **部署**，方便你观察队列积压。
3. **前端手动上传**：改成"经过 kb-api 中转投递队列"意味着单次可能上传 1.5GB，是否接受？还是保留"前端直传 Dify，超过 N 个才走队列"的混合模式？
4. **内网服务器**：是否需要同步部署 RocketMQ？还是先本地开发验证，稳定后再上内网？

---

**确认这份方案后我按 5 个 commit 顺序执行；任何一点想调整告诉我。**
