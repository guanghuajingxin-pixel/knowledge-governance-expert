# DeerFlow 2.0 QA Sidecar（杰克百晓生智能问答 Agent 底座）
# 精简运行镜像：仅 Python 3.12 + harness 依赖；
# 不含 Node/MCP/Docker sandbox（本部署 tool_search 关闭、sandbox=local、无 MCP server）。
# Build context = repo root:
#   docker build -f services/deerflow/Dockerfile -t kge-deerflow .
FROM python:3.12-slim

ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# DeerFlow backend（vendored harness + app/qa_server.py + extensions/kb_tools.py）
COPY services/deerflow/backend/ ./services/deerflow/backend/
# 自定义技能（skills.path = ../skills，相对 cwd=backend 解析）
COPY services/deerflow/skills/ ./services/deerflow/skills/

WORKDIR /app/services/deerflow/backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync

# 运行时数据（config.yaml / SOUL.md / checkpoints.db / memory / threads）
ENV DEER_FLOW_HOME=/app/services/deerflow/data
ENV DEER_FLOW_CONFIG_PATH=/app/services/deerflow/backend/config.yaml

EXPOSE 2027
CMD ["uv", "run", "uvicorn", "app.qa_server:app", "--host", "0.0.0.0", "--port", "2027"]
