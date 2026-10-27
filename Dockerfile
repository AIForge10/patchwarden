# Hosted ResolveLoop API + progress UI. Secrets come from the platform env, never this image.
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md requirements-dev.txt ./
COPY resolveloop ./resolveloop

RUN pip install --no-cache-dir -r requirements-dev.txt \
    && pip install --no-cache-dir -e . --no-deps \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app

USER app

ENV PORT=8000
EXPOSE 8000

# Platforms inject PORT. bind 0.0.0.0 so the load balancer can reach us.
CMD ["sh", "-c", "exec uvicorn resolveloop.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
