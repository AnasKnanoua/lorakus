# syntax=docker/dockerfile:1
# Image de l'API Lorakus, construite en deux etapes :
#   1. "builder" installe les dependances avec uv (outils de construction inclus) ;
#   2. "runtime" ne garde que Python et l'environnement virtuel (image legere).
# Les images de base sont epinglees par empreinte (etape 3 de la PR).

ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- modele
# Modele d'embeddings local (PR 37, ADR 0007) : multilingual-e5-small quantifie en int8
# (licence MIT). Telecharge a la construction, verifie par SHA-256 : un fichier modifie fait
# echouer la construction. Rien n'est telecharge a l'execution.
# - model.onnx : export ONNX int8 de Xenova (Transformers.js), revision epinglee ;
# - tokenizer.json : celui du depot officiel intfloat (contenu fixe par l'empreinte).
# Changer de modele = changer ces deux lignes ET verifier l'evaluation (python -m
# lorakus.ai.providers.check) ; les vecteurs existants sont recalcules (model_id).
FROM scratch AS model
ADD --checksum=sha256:f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193 --chmod=644 \
    https://huggingface.co/Xenova/multilingual-e5-small/resolve/97cb8f96eaed1a1f0dac821239943e854fce9c36/onnx/model_quantized.onnx \
    /models/multilingual-e5-small/model.onnx
ADD --checksum=sha256:0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39 --chmod=644 \
    https://huggingface.co/intfloat/multilingual-e5-small/resolve/main/tokenizer.json \
    /models/multilingual-e5-small/tokenizer.json

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
COPY lorakus_modules ./lorakus_modules
RUN uv sync --locked --no-dev --no-editable

# Migrations des modules, rangees comme dans le depot : alembic.ini les cherche dans
# lorakus_modules/<id>/migrations a cote de lui. Seuls les fichiers de migration sont copies
# (pas de __init__.py) : le code des modules reste celui installe dans .venv.
RUN mkdir -p /migrations/lorakus_modules \
 && find lorakus_modules -path lorakus_modules/_template -prune \
      -o -path '*/migrations/*.py' -print \
    | xargs -r -I{} install -D -m 644 {} /migrations/{}

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

# ORT_DISABLE_TELEMETRY : aucune telemetrie d'ONNX Runtime vers Microsoft (onnx_embedder.py).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    LORAKUS_METRICS_PORT=9464 \
    ORT_DISABLE_TELEMETRY=1

# Utilisateur dedie, sans shell ni repertoire personnel.
RUN groupadd --system --gid 10001 lorakus \
 && useradd --system --uid 10001 --gid lorakus --no-create-home --shell /usr/sbin/nologin lorakus

WORKDIR /app

# Fichiers appartenant a root, lisibles par tous : l'application ne peut pas modifier son propre code.
COPY --from=builder --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --from=builder --chown=root:root /migrations/lorakus_modules ./lorakus_modules
# Modele d'embeddings, en lecture seule comme le code (LORAKUS_EMBEDDING_MODEL_DIR).
COPY --from=model --chown=root:root /models /app/models

USER lorakus

EXPOSE 8000 9464

# Delai de demarrage : chargement du modele d'embeddings compris (quelques secondes sur ARM).
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --start-interval=2s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "--factory", "lorakus.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log"]
