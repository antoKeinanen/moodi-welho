FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/velho.db
RUN groupadd --gid 10001 velho \
    && useradd --uid 10001 --gid velho --no-create-home velho \
    && mkdir /data && chown velho:velho /data
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
USER velho
VOLUME ["/data"]
CMD ["velho"]
