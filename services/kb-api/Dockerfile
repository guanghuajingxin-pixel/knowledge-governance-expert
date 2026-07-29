FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
# Build context is the repo root so the editable kb-common sibling resolves.
COPY services/kb-common/ ./services/kb-common/
COPY services/kb-api/ ./services/kb-api/
WORKDIR /app/services/kb-api
# Cache mount lets parallel builds (faq-service) reuse downloaded wheels.
RUN --mount=type=cache,target=/root/.cache/uv uv sync
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
