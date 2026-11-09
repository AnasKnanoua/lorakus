# Raccourcis de developpement. Tapez "make" pour voir la liste.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
.PHONY: help bootstrap dev test test-all lint format typecheck check \
        db-up db-down db-reset db-shell db-check migrate migration migrate-check \
        image up down logs obs-up obs-check alert-test \
        backup-image backup restore-test

BACKEND := backend
UV := uv --directory $(BACKEND)
COMPOSE := docker compose -f compose.yml -f compose.dev.yml --env-file .env
OBS := $(COMPOSE) -f compose.observability.yml
IMAGE := lorakus-api:dev
BACKUP_IMAGE := lorakus-backup:dev

help: ## Affiche cette aide
> @grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

bootstrap: ## Installe les dependances et les hooks pre-commit
> $(UV) sync
> pre-commit install

dev: ## Lance l'API en local avec rechargement automatique (port 8000)
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

check: lint typecheck test-all db-check obs-check ## Tout verifier avant d'ouvrir une PR

db-up: ## Demarre PostgreSQL en local et attend qu'il soit pret
> $(COMPOSE) up -d --wait postgres

db-down: ## Arrete tous les conteneurs (les donnees sont conservees)
> $(OBS) down

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

up: image db-up ## Lance la pile en conteneurs : PostgreSQL, migrations, API (8001)
> $(COMPOSE) run --rm migrate
> $(COMPOSE) up -d --wait api

down: ## Arrete tous les conteneurs, observabilite comprise (donnees conservees)
> $(OBS) down

logs: ## Affiche les journaux de l'API en direct (Ctrl+C pour quitter)
> $(COMPOSE) logs -f api

obs-up: up ## Ajoute Prometheus (9090), Alertmanager (9093) et Grafana (3000)
> $(OBS) up -d --wait prometheus alertmanager grafana

obs-check: ## Valide Prometheus (config, regles et leurs tests), Alertmanager et Grafana
> python3 -m json.tool infra/observability/grafana/dashboards/lorakus-api.json > /dev/null
> $(OBS) run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
> $(OBS) run --rm --no-deps --entrypoint promtool prometheus test rules /etc/prometheus/tests/lorakus_test.yml
> $(OBS) run --rm --no-deps --entrypoint /bin/sh alertmanager -c 'sed -e "s|__DISCORD_OPS_WEBHOOK_URL__|https://discord.com/api/webhooks/1/test|" /etc/alertmanager/alertmanager.yml.tmpl > /tmp/am.yml && amtool check-config /tmp/am.yml'

alert-test: ## Envoie une alerte de test sur Discord (pile d'observabilite lancee)
> $(OBS) exec alertmanager amtool alert add LorakusTest 'severity="warning"' --annotation='summary="Alerte de test Lorakus"' --alertmanager.url=http://localhost:9093

backup-image: ## Construit l'image de sauvegarde (pg_dump, age, rclone)
> docker build -t $(BACKUP_IMAGE) infra/backup

backup: backup-image db-up ## Sauvegarde chiffree de la base vers B2
> $(COMPOSE) run --rm backup

restore-test: backup-image ## Restaure la derniere sauvegarde dans une base jetable et la verifie
> ./infra/backup/restore-test.sh
