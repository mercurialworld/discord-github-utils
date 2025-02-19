FROM ghcr.io/astral-sh/uv:0.3.0 AS uv
FROM python:3.12.3-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock ./

# comment out editable requirements, since they're not permitted in constraint files
RUN sed -ir 's/^-e /# -e /g' requirements.lock

COPY common/pyproject.toml common/
COPY common/src/ghutils/common/__version__.py common/src/ghutils/common/
RUN mkdir -p common/src/ghutils/common && touch common/src/ghutils/common/__init__.py

COPY bot/pyproject.toml bot/
RUN mkdir -p bot/src/ghutils && touch bot/src/ghutils/app.py

# https://github.com/astral-sh/uv/blob/main/docs/docker.md
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    PYTHONDONTWRITEBYTECODE=1 \
    uv pip install --system \
    --constraint requirements.lock \
    -e bot -e common

COPY common/ common/
COPY bot/ bot/

# NOTE: this must be a list, otherwise signals (eg. SIGINT) are not forwarded to the bot
CMD ["/bin/bash", "-c", "python -m ghutils.app"]

HEALTHCHECK \
    --interval=1m \
    --timeout=30s \
    --start-period=2m \
    --start-interval=15s \
    --retries=3 \
    CMD ["python", "-m", "ghutils.health_check"]
