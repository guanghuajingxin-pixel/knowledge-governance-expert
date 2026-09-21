FROM python:3.11-slim
WORKDIR /app
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/
# Build context is the repo root so the editable kb-common sibling resolves.
COPY services/kb-common/ ./services/kb-common/
COPY services/faq-service/ ./services/faq-service/
WORKDIR /app/services/faq-service
# Cache mount lets parallel builds (kb-api) reuse downloaded wheels.
# datrie (the RAGFlow tokenizer trie) builds a C extension on platforms without wheels.
# 内网链路存在缓存中间盒：http 源 by-hash 索引易 Hash Sum mismatch，固定 https 阿里云镜像并关闭 By-Hash。
RUN --mount=type=cache,target=/root/.cache/uv \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    echo 'Acquire::By-Hash "false";' > /etc/apt/apt.conf.d/99-byhash && \
    apt-get update && apt-get install -y --no-install-recommends build-essential && \
    uv sync && apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/*
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
