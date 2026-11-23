# One Dockerfile, one image per deployable: --build-arg GROUP=api | mcp
# Production pattern for Python + uv: lockfile-driven, non-root, models baked in, no internet at runtime.
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
ARG GROUP=api
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group ${GROUP}
# Download the embedding and reranking models at build time (api image only). A container that pulls
# models on startup is slow to scale and breaks when Hugging Face is down or rate-limits you.
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
ARG RERANK_MODEL=jinaai/jina-reranker-v1-turbo-en
RUN mkdir -p /models && if [ "$GROUP" = "api" ]; then /opt/venv/bin/python -c "\
from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('${EMBED_MODEL}', cache_dir='/models'); TextCrossEncoder('${RERANK_MODEL}', cache_dir='/models')"; fi

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /bootstrap/init /bootstrap/approle /run/secrets/bao && chown -R app /bootstrap
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=app /models /models
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 RAG_MODELS_DIR=/models
WORKDIR /app
COPY rag ./rag
COPY mcp_server ./mcp_server
COPY openbao/policies ./openbao/policies
COPY corpus ./corpus
USER app
