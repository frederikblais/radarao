# Image Python unique (API, workers, migrations, CronJobs). Contexte de build : racine du dépôt.
#   docker build -f services/Dockerfile -t radarao-services .
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/services
COPY services/pyproject.toml services/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY services/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 radarao
WORKDIR /app/services
COPY --from=build --chown=radarao:radarao /app/services /app/services
COPY --chown=radarao:radarao docs/prompts /app/docs/prompts
COPY --chown=radarao:radarao databricks/sql /app/databricks/sql
ENV PATH="/app/services/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
# Rôle choisi par la commande : api (défaut), worker, migrate, ou une tâche (python -m worker.run_task …)
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
