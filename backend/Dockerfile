# syntax=docker/dockerfile:1
# Image de l'API Lorakus, construite en deux etapes :
#   1. "builder" installe les dependances avec uv (outils de construction inclus) ;
#   2. "runtime" ne garde que Python et l'environnement virtuel (image legere).
# Les images de base sont epinglees par empreinte (etape 3 de la PR).

ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependances seules : cette couche reste en cache tant que uv.lock ne change pas.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Code de l'application, installe comme un paquet (non editable).
COPY lorakus ./lorakus
RUN uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    LORAKUS_METRICS_PORT=9464

# Utilisateur dedie, sans shell ni repertoire personnel.
RUN groupadd --system --gid 10001 lorakus \
 && useradd --system --uid 10001 --gid lorakus --no-create-home --shell /usr/sbin/nologin lorakus

WORKDIR /app

# Fichiers appartenant a root, lisibles par tous : l'application ne peut pas modifier son propre code.
COPY --from=builder --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic

USER lorakus

EXPOSE 8000 9464

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --start-interval=2s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "--factory", "lorakus.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log"]
