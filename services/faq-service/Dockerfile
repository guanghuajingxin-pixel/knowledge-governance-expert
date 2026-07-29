FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
# Build context is the repo root so the editable kb-common sibling resolves.
COPY services/kb-common/ ./services/kb-common/
COPY services/faq-service/ ./services/faq-service/
WORKDIR /app/services/faq-service
# Cache mount lets parallel builds (kb-api) reuse downloaded wheels.
RUN --mount=type=cache,target=/root/.cache/uv uv sync
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
