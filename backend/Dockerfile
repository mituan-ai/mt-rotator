FROM ghcr.io/astral-sh/uv:0.10.8 AS uv

FROM python:3.12.11-slim-bookworm AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12.11-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system mtrotator && useradd --system --gid mtrotator --home-dir /app mtrotator
WORKDIR /app
COPY --from=builder --chown=mtrotator:mtrotator /app/.venv /app/.venv
COPY --chown=mtrotator:mtrotator . /app
RUN chmod 0755 /app/docker-entrypoint.sh
USER mtrotator
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "mt_rotator.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
