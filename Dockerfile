FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH="/data/lab.sqlite3"

WORKDIR /app
RUN groupadd --system mcs && useradd --system --gid mcs --home-dir /app mcs \
    && mkdir -p /data && chown mcs:mcs /data
RUN pip install --no-cache-dir uv==0.7.15

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=mcs:mcs . .
RUN uv sync --frozen --no-dev

USER mcs
VOLUME ["/data"]
EXPOSE 8765
CMD ["uvicorn", "lab.api:app", "--host", "0.0.0.0", "--port", "8765", "--no-server-header"]
