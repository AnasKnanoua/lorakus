# Raccourcis de developpement. Tapez "make" pour voir la liste.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
.PHONY: help bootstrap dev test lint format typecheck check

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
