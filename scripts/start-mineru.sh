#!/usr/bin/env bash
# 启动本地 MinerU 文档解析引擎（mineru-api 常驻服务，供 kb-api 解析钉钉/上传的二进制文档）
# 支持 pdf/doc/docx/ppt/pptx/xls/xlsx 的版面/表格/扫描件 OCR，输出 Markdown。
# 依赖：uv（自动准备 Python 3.12 虚拟环境）。首次解析会自动下载模型（约数 GB），
# 国内网络默认走 ModelScope（MINERU_MODEL_SOURCE=modelscope）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MINERU_DIR="$ROOT_DIR/services/mineru"
VENV_PY="$MINERU_DIR/.venv/bin/python"

export MINERU_PORT="${MINERU_PORT:-2028}"
export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"
# macOS Apple Silicon 自动用 MPS、无 GPU 回退 CPU；可用 MINERU_DEVICE_MODE 强制 cpu/mps
export MINERU_DEVICE_MODE="${MINERU_DEVICE_MODE:-}"

mkdir -p "$MINERU_DIR"
cd "$MINERU_DIR"

# 首次运行：准备 Python 3.12 环境并安装 mineru[core]
if [ ! -x "$VENV_PY" ]; then
  echo "[mineru] creating Python 3.12 venv and installing mineru[core] (may take a while)..."
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -U "mineru[core]" \
    -i https://mirrors.aliyun.com/pypi/simple
fi

# 预下载模型（可选；避免首个请求长时间等待）。失败不阻断启动（首次解析时会重试）。
if [ "${MINERU_PREDOWNLOAD_MODELS:-0}" = "1" ]; then
  echo "[mineru] pre-downloading models (MINERU_PREDOWNLOAD_MODELS=1)..."
  .venv/bin/mineru-models-download || true
fi

echo "[mineru] starting mineru-api on http://127.0.0.1:${MINERU_PORT} (model source: ${MINERU_MODEL_SOURCE})"
exec .venv/bin/mineru-api --host 127.0.0.1 --port "${MINERU_PORT}"
