# Raccourcis de developpement. Tapez "make" pour voir la liste.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
.PHONY: help bootstrap dev test lint format typecheck check db-up db-down db-reset db-shell db-check

BACKEND := backend
UV := uv --directory $(BACKEND)

help: ## Affiche cette aide
> @grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Installe les dependances et les hooks pre-commit
> $(UV) sync
> pre-commit install

dev: ## Lance l'API en local avec rechargement automatique
> $(UV) run uvicorn --factory lorakus.api.app:create_app --reload --host 127.0.0.1 --port 8000

test: ## Lance les tests
> $(UV) run pytest

lint: ## Verifie le style et les erreurs courantes
> $(UV) run ruff check .
> $(UV) run ruff format --check .

format: ## Formate le code et corrige ce qui peut l'etre automatiquement
> $(UV) run ruff format .
> $(UV) run ruff check --fix .

typecheck: ## Verifie les types (pyright strict)
> $(UV) run pyright

check: lint typecheck test ## Tout verifier avant d'ouvrir une PR


COMPOSE := docker compose -f compose.yml -f compose.dev.yml --env-file .env

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
