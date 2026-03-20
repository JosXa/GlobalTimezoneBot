FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock README.md bot.py commands.txt ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app /app

USER 65532:65532

CMD ["globaltimezonebot"]
