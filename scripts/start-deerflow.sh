#!/usr/bin/env bash
# 启动 DeerFlow 2.0 QA Sidecar（智能问答 Agent 底座）
# 依赖：uv（自动准备 Python 3.12 虚拟环境）、kb-api 已在运行（提供 bootstrap/检索内部接口）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/services/deerflow/backend"

# 内部服务间令牌（与 kb-api 的 KB_INTERNAL_TOKEN 保持一致；默认值仅用于本地开发）
export KB_INTERNAL_TOKEN="${KB_INTERNAL_TOKEN:-kge-internal-dev-token}"
export KB_API_URL="${KB_API_URL:-http://127.0.0.1:8000}"
export DEERFLOW_PORT="${DEERFLOW_PORT:-2027}"
export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$ROOT_DIR/services/deerflow/data}"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$BACKEND_DIR/config.yaml}"

mkdir -p "$DEER_FLOW_HOME"

cd "$BACKEND_DIR"

# 首次运行：准备 Python 3.12 环境并安装依赖
if [ ! -d ".venv" ]; then
  echo "[deerflow] creating Python 3.12 venv..."
  uv python install 3.12
  uv venv --python 3.12 .venv
  uv sync
fi

echo "[deerflow] starting QA sidecar on http://127.0.0.1:${DEERFLOW_PORT}"
exec uv run uvicorn app.qa_server:app --host 127.0.0.1 --port "${DEERFLOW_PORT}"
