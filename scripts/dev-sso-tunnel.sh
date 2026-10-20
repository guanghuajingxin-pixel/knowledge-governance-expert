#!/usr/bin/env bash
# 本地开发隧道：把远端服务器（10.10.166.2）上的内网服务转发到本地回环地址。
# 目前转发两类服务，本地无需运行对应容器：
#   1. Keycloak 身份中心 → 127.0.0.1:8180
#   2. XXL-Job 调度中心（3.4.2，容器 xxljob-admin）→ 127.0.0.1:8088
#
# 配合仓库根 .env 的：
#   AUTH_PROVIDER=keycloak
#   OIDC_ISSUER=http://127.0.0.1:8180/realms/jack
#   XXL_JOB_ADMIN_URL=http://127.0.0.1:8088
# 远端 Keycloak 的 KC_HOSTNAME 即 http://127.0.0.1:8180，浏览器回调 / 后端 JWKS /
# token issuer 三者地址天然一致，隧道建立后零额外改造。
#
# 用法：
#   ./scripts/dev-sso-tunnel.sh          # 建立隧道（幂等，已在运行则跳过）
#   ./scripts/dev-sso-tunnel.sh stop     # 停止隧道
#   ./scripts/dev-sso-tunnel.sh status   # 查看状态
set -euo pipefail

KEY="${KGE_SSH_KEY:-$HOME/.ssh/id_ed25519_deploy_10.10.166.2}"
HOST="${KGE_SSH_HOST:-jack@10.10.166.2}"
LOCAL_PORT="${KGE_SSO_LOCAL_PORT:-8180}"
XXL_LOCAL_PORT="${KGE_XXL_LOCAL_PORT:-8088}"
PID_FILE="/tmp/kge-sso-tunnel.pid"
LOG_FILE="/tmp/kge-sso-tunnel.log"
OIDC_URL="http://127.0.0.1:${LOCAL_PORT}/realms/jack/.well-known/openid-configuration"
XXL_URL="http://127.0.0.1:${XXL_LOCAL_PORT}/auth/login"

running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-start}" in
  start)
    if running; then
      echo "[sso-tunnel] 已在运行 (PID $(cat "$PID_FILE"))，无需重复启动"
      exit 0
    fi
    # 本地 Keycloak 容器（jack-identity）会占用 8180，本地 XXL-Job 容器会占用 8080/8081/8082，
    # 先确认隧道端口空闲
    for port in "$LOCAL_PORT" "$XXL_LOCAL_PORT"; do
      if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "[sso-tunnel] 端口 $port 已被占用（本地 Keycloak / XXL-Job 容器未停？）：" >&2
        lsof -nP -iTCP:"$port" -sTCP:LISTEN | head -3 >&2
        echo "先停掉本地对应容器：docker stop jack-identity-keycloak-1 jack-identity-database-1 xxl-job-admin kge-xxl-job-admin kge-xxl-job-mysql" >&2
        exit 1
      fi
    done
    nohup ssh -N -i "$KEY" \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -o StrictHostKeyChecking=accept-new \
      -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:8180" \
      -L "127.0.0.1:${XXL_LOCAL_PORT}:127.0.0.1:8088" "$HOST" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if curl -fsS "$OIDC_URL" >/dev/null 2>&1; then
      echo "[sso-tunnel] 隧道已建立：本地 127.0.0.1:${LOCAL_PORT} → ${HOST#*@} 的 Keycloak (realm=jack)"
    else
      echo "[sso-tunnel] 隧道启动失败，日志见 $LOG_FILE" >&2
      rm -f "$PID_FILE"
      exit 1
    fi
    if curl -fsS "$XXL_URL" >/dev/null 2>&1; then
      echo "[sso-tunnel] XXL-Job 调度中心可达：本地 127.0.0.1:${XXL_LOCAL_PORT} → ${HOST#*@} 的 xxljob-admin (3.4.2)"
    else
      echo "[sso-tunnel] 警告：XXL-Job 调度中心不可达（${XXL_URL}），kb-api 定时同步会降级跳过" >&2
    fi
    ;;
  stop)
    if running; then
      kill "$(cat "$PID_FILE")" && rm -f "$PID_FILE"
      echo "[sso-tunnel] 隧道已停止"
    else
      echo "[sso-tunnel] 隧道未在运行"
    fi
    ;;
  status)
    if running; then
      echo "[sso-tunnel] 运行中 (PID $(cat "$PID_FILE"))"
      curl -fsS "$OIDC_URL" >/dev/null 2>&1 && echo "[sso-tunnel] Keycloak 可达" || echo "[sso-tunnel] 警告：Keycloak 不可达，检查网络"
      curl -fsS "$XXL_URL" >/dev/null 2>&1 && echo "[sso-tunnel] XXL-Job 调度中心可达" || echo "[sso-tunnel] 警告：XXL-Job 调度中心不可达，kb-api 定时同步会降级跳过"
    else
      echo "[sso-tunnel] 未运行（./scripts/dev-sso-tunnel.sh 启动）"
    fi
    ;;
  *)
    echo "用法：$0 [start|stop|status]" >&2
    exit 1
    ;;
esac
