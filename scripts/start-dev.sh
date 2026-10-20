#!/usr/bin/env bash
# 本地开发统一启动脚本 —— 认证策略在「服务启动时」确定，二选一（对话指令约定：
# 「以 local 模式启动」= 本地登录策略；「以 keycloak 模式启动 / 默认启动」= Keycloak 统一登录）：
#
#   scripts/start-dev.sh local      本地登录策略：AUTH_PROVIDER=local，账号存本地 PG（users 表），
#                                   密码登录 + 门户「用户管理/角色管理」，权限由系统自己管理。
#                                   无本地账号时先运行 scripts/seed_admin.py 建号。
#   scripts/start-dev.sh keycloak   Keycloak 策略：经 SSH 隧道调用 10.10.166.2 上的身份中心统一登录
#                                   （本地调试也一样；不再有写死令牌的免密自动登录通道）。
#                                   隧道由 scripts/dev-sso-tunnel.sh 维护，本地 127.0.0.1:8180 →
#                                   远端 Keycloak（realm=jack），issuer 三方一致零改造。
#
# 约定：服务端（10.10.166.2）默认使用 KEYCLOAK 登录。
#
# 用法：
#   scripts/start-dev.sh <local|keycloak> [start]   # 启动（默认）
#   scripts/start-dev.sh <mode> stop               # 停止全部
#   scripts/start-dev.sh <mode> restart             # 重启
#   scripts/start-dev.sh status                    # 查看状态（无需模式）
#
# 进程：kb-api :8000 / faq-service :8004 / web :8080（永久口径，禁用 3000）/ portal :80
# PID 与日志：/tmp/kge-dev/<name>.{pid,log}（kb-worker 默认不启动，需要时手动：
#   cd services/kb-api && uv run celery -A app.worker worker -Q ingestion -l info）
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="/tmp/kge-dev"
KC_ENV_FILE="$REPO/deploy/keycloak/.env"
mkdir -p "$RUN_DIR"

# ---------------------------------------------------------------- 认证环境

auth_env_local() {
  echo "AUTH_PROVIDER=local"
}

auth_env_keycloak() {
  # 隧道：本地 127.0.0.1:8180 → 10.10.166.2 的 Keycloak（issuer 一致，token 校验零改造）
  # 隧道脚本的提示输出走 stderr，避免污染返回的变量串
  "$REPO/scripts/dev-sso-tunnel.sh" start >&2
  local secret=""
  if [[ -f "$KC_ENV_FILE" ]]; then
    secret="$(grep -E '^PLATFORM_KEY_MANAGER_SECRET=' "$KC_ENV_FILE" | head -1 | cut -d= -f2- || true)"
  fi
  if [[ -z "$secret" ]]; then
    echo "[start-dev] 警告：未在 $KC_ENV_FILE 找到 PLATFORM_KEY_MANAGER_SECRET，" >&2
    echo "[start-dev] 统一登录可用，但门户「用户管理」的身份中心管理接口不可用（503）。" >&2
  fi
  echo "AUTH_PROVIDER=keycloak"
  echo "OIDC_ISSUER=http://127.0.0.1:8180/realms/jack"
  echo "OIDC_ADMIN_CLIENT_ID=platform-key-manager"
  [[ -n "$secret" ]] && echo "OIDC_ADMIN_CLIENT_SECRET=$secret"
}

check_local_accounts() {
  # local 模式：本地库无账号时提示建号（不阻断，用户可能已有自己的账号）
  local count
  count="$(cd "$REPO/services/kb-common" && uv run python -c "
import asyncio, sys
from sqlalchemy import text
from kb_common.database import SessionLocal

async def main():
    async with SessionLocal() as s:
        print((await s.execute(text('SELECT count(*) FROM users'))).scalar())

asyncio.run(main())
" 2>/dev/null || echo '?')"
  if [[ "$count" == "0" ]]; then
    echo "[start-dev] 本地库尚无任何账号，请先建管理员（本地登录策略必需）：" >&2
    echo "  cd services/kb-common && read -s KGE_BOOTSTRAP_ADMIN_PASSWORD && export KGE_BOOTSTRAP_ADMIN_PASSWORD && KGE_BOOTSTRAP_ADMIN_USERNAME=admin uv run python ../../scripts/seed_admin.py" >&2
  fi
}

# ---------------------------------------------------------------- 进程管理

proc_running() {
  local name="$1"
  [[ -f "$RUN_DIR/$name.pid" ]] && kill -0 "$(cat "$RUN_DIR/$name.pid")" 2>/dev/null
}

start_proc() {
  local name="$1" workdir="$2" health="$3"; shift 3
  if proc_running "$name"; then
    echo "[start-dev] $name 已在运行 (PID $(cat "$RUN_DIR/$name.pid"))"
    return 0
  fi
  # 端口占用预检：绝不覆盖已在运行的外部进程（提示用户先停旧服务再启动）
  local port; port="$(echo "$health" | awk -F: '{print $NF}' | sed 's|/.*||')"
  local occupier; occupier="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  if [[ -n "$occupier" ]]; then
    echo "[start-dev] $name 启动中止：端口 $port 已被进程 $occupier 占用。" >&2
    echo "[start-dev] 若为旧的开发服务，请先停止（或用本脚本 stop 清理上次由脚本启动的进程）后重试。" >&2
    return 1
  fi
  (cd "$workdir" && nohup "$@" > "$RUN_DIR/$name.log" 2>&1 & echo $! > "$RUN_DIR/$name.pid")
  sleep 1
  if ! proc_running "$name"; then
    echo "[start-dev] $name 启动失败，日志 $RUN_DIR/$name.log" >&2
    rm -f "$RUN_DIR/$name.pid"
    return 1
  fi
  local pid; pid="$(cat "$RUN_DIR/$name.pid")"
  # 就绪等待（最多 40s）：后端 /health 或前端首页可达
  local waited=0
  until curl -fsS -m 2 "$health" >/dev/null 2>&1; do
    kill -0 "$pid" 2>/dev/null || { echo "[start-dev] $name 进程异常退出，日志 $RUN_DIR/$name.log" >&2; rm -f "$RUN_DIR/$name.pid"; return 1; }
    ((waited += 2)); [[ $waited -gt 40 ]] && break
    sleep 2
  done
  echo "[start-dev] $name 已启动 (PID $pid)，日志 $RUN_DIR/$name.log"
}

stop_proc() {
  local name="$1"
  if proc_running "$name"; then
    local pid; pid="$(cat "$RUN_DIR/$name.pid")"
    kill "$pid" 2>/dev/null || true
    # pnpm dev 会派生 vite 子进程：连同直接子进程一并回收，避免端口残留
    pkill -TERM -P "$pid" 2>/dev/null || true
    echo "[start-dev] $name 已停止"
  fi
  rm -f "$RUN_DIR/$name.pid"
}

status_all() {
  for name in kb-api faq-service web portal; do
    if proc_running "$name"; then
      echo "[start-dev] $name 运行中 (PID $(cat "$RUN_DIR/$name.pid"))"
    else
      echo "[start-dev] $name 未运行"
    fi
  done
  curl -fsS -m 2 http://127.0.0.1:8000/api/v1/auth/config >/dev/null 2>&1 \
    && echo "[start-dev] kb-api 认证模式: $(curl -fsS -m 2 http://127.0.0.1:8000/api/v1/auth/config | head -c 60)" \
    || echo "[start-dev] kb-api 未就绪（启动约需 5-15s）"
  "$REPO/scripts/dev-sso-tunnel.sh" status
}

start_all() {
  local mode="$1"
  local auth_env
  if [[ "$mode" == "local" ]]; then
    auth_env="$(auth_env_local)"
  else
    auth_env="$(auth_env_keycloak)"
  fi
  # shellcheck disable=SC2312
  while IFS='=' read -r key value; do
    export "$key=$value"
  done <<< "$auth_env"
  echo "[start-dev] 认证模式: $AUTH_PROVIDER"
  if [[ "$mode" == "local" ]]; then
    check_local_accounts
  else
    # keycloak 模式下旧本地 JWT / 写死令牌会话全部失效（authenticate 仅认身份中心令牌）
    :
  fi

  start_proc kb-api "$REPO/services/kb-api" "http://127.0.0.1:8000/health" \
    uv run uvicorn app.main:app --reload --port 8000
  start_proc faq-service "$REPO/services/faq-service" "http://127.0.0.1:8004/health" \
    uv run uvicorn app.main:app --reload --port 8004
  start_proc web "$REPO/web" "http://127.0.0.1:8080" \
    pnpm dev
  start_proc portal "$REPO/portal" "http://127.0.0.1:80" \
    env PORTAL_API_TARGET=http://127.0.0.1:8000 pnpm dev

  echo
  echo "[start-dev] 全部进程已按 $mode 模式启动；kb-api 就绪约需 5-15s"
  echo "[start-dev] 入口：web http://127.0.0.1:8080 · 门户 http://127.0.0.1"
}

stop_all() {
  for name in portal web faq-service kb-api; do stop_proc "$name"; done
  echo "[start-dev] 提示：keycloak 模式的 SSO 隧道保留运行（scripts/dev-sso-tunnel.sh stop 可停）"
}

# ---------------------------------------------------------------- 入口

# status / stop 免模式直用
case "${1:-}" in
  status) status_all; exit 0 ;;
  stop) stop_all; exit 0 ;;
esac

mode="${1:-}"
if [[ "$mode" != "local" && "$mode" != "keycloak" ]]; then
  echo "用法：$0 <local|keycloak> [start|restart] | status | stop" >&2
  echo "  local     本地登录策略（账号存本地 PG，密码登录）" >&2
  echo "  keycloak  Keycloak 统一登录（经隧道调用 10.10.166.2 身份中心；服务端默认模式）" >&2
  echo "  status    查看运行状态（无需模式）" >&2
  echo "  stop      停止全部（无需模式）" >&2
  exit 1
fi

action="${2:-start}"
case "$action" in
  start) start_all "$mode" ;;
  restart) stop_all; sleep 1; start_all "$mode" ;;
  *) echo "未知子命令：${action}（可选 start|restart；status/stop 直接作首参数）" >&2; exit 1 ;;
esac
