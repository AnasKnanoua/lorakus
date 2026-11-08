# Raccourcis de developpement. Tapez "make" pour voir la liste.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
.PHONY: help bootstrap dev test test-all lint format typecheck check \
        db-up db-down db-reset db-shell db-check migrate migration migrate-check image image-run

BACKEND := backend
UV := uv --directory $(BACKEND)
COMPOSE := docker compose -f compose.yml -f compose.dev.yml --env-file .env
IMAGE := lorakus-api:dev

help: ## Affiche cette aide
> @grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

bootstrap: ## Installe les dependances et les hooks pre-commit
> $(UV) sync
> pre-commit install

dev: ## Lance l'API en local avec rechargement automatique
> LORAKUS_LOG_FORMAT=console $(UV) run uvicorn --factory lorakus.api.app:create_app --reload --host 127.0.0.1 --port 8000 --no-access-log

test: ## Tests unitaires (sans base de donnees)
> $(UV) run pytest -m "not integration"

test-all: db-up migrate ## Tous les tests, y compris avec PostgreSQL
> $(UV) run pytest

lint: ## Verifie le style et les erreurs courantes
> $(UV) run ruff check .
> $(UV) run ruff format --check .

format: ## Formate le code et corrige ce qui peut l'etre automatiquement
> $(UV) run ruff format .
> $(UV) run ruff check --fix .

typecheck: ## Verifie les types (pyright strict)
> $(UV) run pyright

check: lint typecheck test-all db-check ## Tout verifier avant d'ouvrir une PR

db-up: ## Demarre PostgreSQL en local et attend qu'il soit pret
> $(COMPOSE) up -d --wait postgres

db-down: ## Arrete PostgreSQL (les donnees sont conservees)
> $(COMPOSE) down

db-reset: ## SUPPRIME la base locale et la recree a neuf
> $(COMPOSE) down -v
> $(COMPOSE) up -d --wait postgres

db-shell: ## Ouvre une console SQL en tant que lorakus_app
> $(COMPOSE) exec postgres psql -U lorakus_app -d lorakus

db-check: ## Verifie les roles et permissions PostgreSQL
> ./infra/postgres/check-roles.sh

migrate: ## Applique toutes les migrations (role lorakus_migrator)
> $(UV) run alembic upgrade heads

migration: ## Nouvelle migration : make migration BRANCH=core MSG="description"
> @test -n "$(BRANCH)" -a -n "$(MSG)" || (echo 'Usage : make migration BRANCH=core MSG="description"'; exit 1)
> $(UV) run alembic revision --autogenerate --head=$(BRANCH)@head -m "$(MSG)"

migrate-check: ## Verifie que les migrations sont rejouables (montee, descente, montee)
> $(UV) run alembic upgrade heads
> $(UV) run alembic downgrade base
> $(UV) run alembic upgrade heads
> $(UV) run alembic check

image: ## Construit l'image Docker de l'API
> docker build -t $(IMAGE) $(BACKEND)

image-run: db-up ## Lance l'image en local, reliee a PostgreSQL (API 8001, metriques 9464)
> docker run --rm --name lorakus-api-dev --network lorakus_internal --env-file .env -e LORAKUS_DB_HOST=postgres -p 127.0.0.1:8001:8000 -p 127.0.0.1:9464:9464 $(IMAGE)
