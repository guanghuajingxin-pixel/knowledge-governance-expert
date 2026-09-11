# 钉钉知识库 → Dify 定时增量同步服务

将钉钉知识库（wiki）中的文档定时、增量同步到 Dify 知识库。后端采用 Python + FastAPI + APScheduler + SQLite。

## 功能

- 钉钉知识库目录树递归遍历（分页拉取，已验证）
- 本地文件（DOCUMENT）走钉钉开放平台三步下载链路
- 在线文档（ALIDOC）通过 `dws` CLI 导出为 markdown / docx / pdf
- Dify 1.x 数据集自动创建、文档上传 / 更新 / 删除
- 增量同步：基于节点元数据指纹 + 内容哈希，无变化不重复上传
- 定时任务（cron）与手动触发
- 运行监控、日志、失败记录、钉钉群机器人告警
- REST API + Swagger 文档（`/docs`）

## 目录结构

```text
kb-sync-service/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 环境变量配置
│   ├── database.py          # SQLAlchemy 引擎/会话
│   ├── models.py            # 数据模型
│   ├── schemas.py           # 请求/响应模型
│   ├── api/routes.py        # REST 路由
│   └── services/
│       ├── dingtalk_client.py  # 钉钉 API 客户端
│       ├── dify_client.py      # Dify API 客户端
│       ├── export_service.py   # dws 导出封装
│       ├── sync_engine.py      # 同步引擎
│       ├── scheduler.py        # APScheduler 调度
│       └── alert.py            # 钉钉机器人告警
├── data/                    # SQLite + 下载缓存（运行时生成）
├── logs/                    # 日志（运行时生成）
├── requirements.txt
└── .env.example
```

## 环境要求

- Python 3.10+
- Node.js 18+（仅在线文档导出需要 `dws` CLI）
- 钉钉企业内部应用：`Wiki.Workspace.Read`、`Wiki.Node.Read`、`Document.WorkspaceDocument.Read`、`Storage.DownloadInfo.Read` 权限
- Dify 1.x 的 Dataset API Key（`/v1` 地址）

## 快速开始（Linux）

```bash
cd kb-sync-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 安装并登录 dws CLI（在线文档导出必需）
npm install -g dingtalk-workspace-cli
dws auth login --client-id <AppKey> --client-secret <AppSecret>

# 配置
cp .env.example .env
vim .env   # 填入 AppKey / AppSecret / Dify Key 等

# 启动
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://<ip>:8000/admin` 打开管理后台，`http://<ip>:8000/docs` 查看接口文档。默认后台账号 `admin` / `admin123`（请修改）。

## 配置项（.env）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DINGTALK_APP_KEY` | 钉钉应用 AppKey | - |
| `DINGTALK_APP_SECRET` | 钉钉应用 AppSecret | - |
| `DINGTALK_OPERATOR_ID` | 有下载权限的用户 unionId | - |
| `DIFY_BASE_URL` | Dify API 地址 | `http://10.10.166.81/v1` |
| `DIFY_DATASET_API_KEY` | Dify Dataset API Key | - |
| `DIFY_DEFAULT_PERMISSION` | 新建数据集权限 | `all_team_members` |
| `DWS_BIN` | dws 可执行文件 | `dws` |
| `APP_PORT` | 服务端口 | `8000` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 后台账号 | `admin` / `admin123` |
| `SECRET_KEY` | 登录 token 盐 | `change_me` |
| `DINGTALK_WEBHOOK` | 钉钉群机器人 webhook | 空（不告警） |
| `ALERT_FAILURE_THRESHOLD` | 失败数达到该值触发告警 | `1` |
| `DEFAULT_DELETE_POLICY` | 默认删除策略 `keep`/`sync` | `keep` |
| `EXPORT_FORMAT` | 在线文档导出格式 | `markdown` |
| `MAX_DEPTH` | 目录遍历最大深度 | `10` |

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录获取 token |
| GET | `/api/dashboard` | 工作台统计 |
| GET/POST | `/api/sources` | 同步源列表/新增 |
| GET/PUT/DELETE | `/api/sources/{id}` | 同步源详情/修改/删除 |
| POST | `/api/sources/{id}/test` | 测试连接（钉钉 + Dify + dws） |
| POST | `/api/sources/{id}/sync` | 手动触发同步 |
| GET/POST | `/api/jobs` | 定时任务列表/新增 |
| PUT/DELETE | `/api/jobs/{id}` | 修改/删除任务 |
| POST | `/api/jobs/{id}/run` | 手动执行任务 |
| POST | `/api/jobs/{id}/toggle` | 启用/停用任务 |
| GET | `/api/runs` / `/api/runs/{id}` | 运行记录/详情 |
| GET | `/api/failures` | 失败记录 |
| GET | `/api/logs` | 运行日志 |
| GET/PUT | `/api/settings` | 服务设置 |

除登录外，请求需带 `Authorization: Bearer <token>`。

## 同步源字段

| 字段 | 说明 |
|------|------|
| `name` | 同步源名称 |
| `workspace_id` | 钉钉知识库 workspaceId |
| `root_node_id` | 起始目录 nodeId（知识库根节点） |
| `start_dir` | 备注的起始目录（展示用） |
| `dify_dataset_name` | 目标 Dify 数据集名称（不存在会自动创建） |
| `delete_policy` | `keep` 保留 Dify 文档 / `sync` 删除钉钉侧已不存在的文档 |
| `enabled` | 是否启用 |

获取 `workspace_id` / `root_node_id`：调用 `GET /v2.0/wiki/workspaces`（也可用本服务“测试连接”返回的知识库列表）。

## 定时任务 cron 示例

| cron | 含义 |
|------|------|
| `*/10 * * * *` | 每 10 分钟 |
| `0 2 * * *` | 每天凌晨 2 点 |
| `0 */6 * * *` | 每 6 小时 |

## systemd 部署

```bash
sudo cp deploy/kb-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kb-sync
sudo systemctl status kb-sync
```

## 注意事项

- Dify 1.x 更新文档使用 `POST /datasets/{id}/documents/{doc_id}/update-by-file`（不是 PATCH）。
- 下载 OSS 签名 URL 有效期约 15 分钟，服务会在同步时即时下载，不长期缓存。
- 在线表格（`.axls`）等特殊类型可能需将 `dws doc export` 替换为 `dws sheet export`，当前默认按在线文档处理。
- `operatorId` 对应用户需具备目标知识库的下载/导出权限。
