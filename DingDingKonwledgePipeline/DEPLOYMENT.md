# 钉钉知识库流水线：部署与更新手册

本文记录截至 2026-09-07 的正式环境结构和维护步骤。服务器凭据、令牌及其他密钥不写入本文；实际运行配置位于 `kb-sync-service/.env`。

## 正式环境

| 项目 | 当前值 |
| --- | --- |
| 服务器 | `10.10.166.2`（SSH 22） |
| 项目目录 | `/opt/kb-sync` |
| Git 分支 | `main` |
| 后端 | FastAPI/Uvicorn，`127.0.0.1:8000` |
| 后端服务 | `kb-sync.service`，以用户 `jack` 运行，已设为开机启动 |
| 前端 | Vue/Vite 构建产物：`/opt/kb-sync/kb-sync-web/dist` |
| 网关 | Nginx 监听 `80`，站点配置：`/etc/nginx/sites-available/kb-sync` |

## 架构

```text
浏览器
  │ HTTP :80
  ▼
Nginx
  ├─ /             → /opt/kb-sync/kb-sync-web/dist（Vue 单页应用）
  └─ /api/         → http://127.0.0.1:8000（反向代理）
                         │
                         ▼
                    kb-sync.service
                    Uvicorn / FastAPI
                         │
           ┌─────────────┴─────────────┐
           ▼                           ▼
       钉钉知识库                    Dify 数据集
```

后端的 SQLite 数据库、下载文件和日志分别位于 `kb-sync-service/data/`、`kb-sync-service/data/downloads/` 与 `kb-sync-service/logs/`。这些运行数据不进入 Git。

## 配置与安全

为了让内部成员克隆后可直接运行，实际 `.env` 已纳入本私有 GitLab 仓库。该文件包含生产凭据，仓库必须保持私有，并只授予必要成员访问权限。

- 不要将仓库改为公开，也不要把代码镜像到公开仓库。
- 不要在 Issue、Wiki、聊天记录或部署日志中复制 `.env` 内容。
- `.env.example` 只保留占位符，供脱离生产环境时创建新配置使用。
- 若 GitLab 成员范围扩大、仓库泄露，或生产凭据曾被外发，应立即在钉钉、Dify 和服务器侧轮换相应密钥，并更新 `.env` 后提交。

## 首次将现有服务器切换为 Git 工作区

当前线上 `/opt/kb-sync` 是直接部署的目录，尚不是 Git 工作区。执行以下步骤前，先选择业务空闲窗口；它们会保留当前目录的完整备份和运行数据。

```bash
ssh jack@10.10.166.2
sudo systemctl stop kb-sync.service

# 完整备份当前线上版本及 SQLite/下载数据
sudo cp -a /opt/kb-sync "/opt/kb-sync-backup-$(date +%F-%H%M%S)"

# 将当前代码目录关联到 GitLab；若检出提示未跟踪文件冲突，保留备份后再处理冲突文件
cd /opt/kb-sync
git init
git remote add origin http://10.10.166.3/JACK_AI-Exploer-GMY/DingDingKonwledgePipeline.git
git fetch origin main
git checkout -B main --track origin/main

# 运行数据不在 Git 中，确认仍存在；若缺失，从刚创建的备份恢复
test -f kb-sync-service/data/sync.db || sudo cp -a /opt/kb-sync-backup-*/kb-sync-service/data kb-sync-service/

cd kb-sync-service
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd ../kb-sync-web
npm ci
npm run build

sudo systemctl start kb-sync.service
sudo systemctl status kb-sync.service --no-pager
curl -fsS http://127.0.0.1:8000/docs > /dev/null && echo 'API healthy'
```

> 若系统没有 `sudo` 权限，请由具备管理员权限的运维人员执行服务启停与 Nginx 配置操作。

## 日常更新流程

将代码推送到 GitLab `main` 后，在服务器执行：

```bash
ssh jack@10.10.166.2
cd /opt/kb-sync

# 更新后端和前端源代码；查看变更，确认没有意外内容
git pull --ff-only origin main
git log --oneline -3

# 后端依赖有变化时必须执行；重复执行安全
cd kb-sync-service
.venv/bin/pip install -r requirements.txt

# 前端每次更新均重新构建
cd ../kb-sync-web
npm ci
npm run build

# 重启后端使 Python 代码生效
sudo systemctl restart kb-sync.service
sudo systemctl status kb-sync.service --no-pager

# 验证后端与 Nginx 入口
curl -fsS http://127.0.0.1:8000/docs > /dev/null && echo 'API healthy'
curl -fsSI http://127.0.0.1/ | head -n 1
```

如果本次改动包含 `/etc/nginx/sites-available/kb-sync`，需额外执行：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

如果本次改动包含 [deploy/kb-sync.service](kb-sync-service/deploy/kb-sync.service)，需额外执行：

```bash
sudo cp /opt/kb-sync/kb-sync-service/deploy/kb-sync.service /etc/systemd/system/kb-sync.service
sudo systemctl daemon-reload
sudo systemctl restart kb-sync.service
```

## 回滚

先查找可用版本：

```bash
cd /opt/kb-sync
git log --oneline --decorate -10
```

确认目标提交号后，执行以下命令回滚代码并重建前端。`git reset --hard` 会丢弃服务器中未提交的代码修改，因此只在确认没有需要保留的线上临时改动时使用；运行数据目录不会被 Git 操作删除。

```bash
git reset --hard <目标提交号>
cd kb-sync-service && .venv/bin/pip install -r requirements.txt
cd ../kb-sync-web && npm ci && npm run build
sudo systemctl restart kb-sync.service
curl -fsS http://127.0.0.1:8000/docs > /dev/null && echo 'Rollback healthy'
```

恢复到最新 `main`：

```bash
cd /opt/kb-sync
git pull --ff-only origin main
```

## 排障命令

```bash
# 服务状态与最近日志
sudo systemctl status kb-sync.service --no-pager
sudo journalctl -u kb-sync.service -n 200 --no-pager

# Nginx 配置与错误检查
sudo nginx -t
sudo tail -n 100 /var/log/nginx/error.log

# 本机 API 健康检查
curl -i http://127.0.0.1:8000/docs
```
