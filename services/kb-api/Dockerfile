FROM python:3.11-slim
WORKDIR /app
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/
# Build context is the repo root so the editable kb-common sibling resolves.
COPY services/kb-common/ ./services/kb-common/
COPY services/kb-api/ ./services/kb-api/
# DB 迁移与种子脚本（容器内可执行 alembic upgrade head / seed_admin.py）
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
WORKDIR /app/services/kb-api
# Cache mount lets parallel builds (faq-service) reuse downloaded wheels.
RUN --mount=type=cache,target=/root/.cache/uv uv sync
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
