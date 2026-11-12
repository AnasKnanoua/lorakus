# Raccourcis de developpement. Tapez "make" pour voir la liste.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
.PHONY: help bootstrap dev test test-all lint format typecheck check \
        db-up db-down db-reset db-shell db-check migrate migration migrate-check \
        image up down logs obs-up obs-check alert-test \
        backup-image backup restore-test \
        pr merge deploy deploy-skip-staging rollback prod-status release-pr release new-module

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
> cd frontend && pnpm install --frozen-lockfile
> pre-commit install

dev: ## Lance l'API en local avec rechargement automatique (port 8000)
> LORAKUS_LOG_FORMAT=console $(UV) run uvicorn --factory lorakus.api.app:create_app --reload --host 127.0.0.1 --port 8000 --no-access-log

test: ## Tests unitaires (sans base de donnees)
> $(UV) run pytest -m "not integration"

new-module: ## Cree un module : make new-module ID=academic PREFIX=acad NAME="Academic Manager"
> @test -n "$(ID)" -a -n "$(PREFIX)" -a -n "$(NAME)" || { echo 'Usage : make new-module ID=academic PREFIX=acad NAME="Academic Manager"'; exit 2; }
> $(UV) run python scripts/new_module.py "$(ID)" "$(PREFIX)" "$(NAME)" && $(UV) sync

test-all: db-up migrate ## Tous les tests, y compris avec PostgreSQL
> $(UV) run pytest

lint: ## Verifie le style, les erreurs courantes et les frontieres d'architecture
> $(UV) run ruff check .
> $(UV) run ruff format --check .
> $(UV) run lint-imports

format: ## Formate le code et corrige ce qui peut l'etre automatiquement
> $(UV) run ruff format .
> $(UV) run ruff check --fix .

typecheck: ## Verifie les types (pyright strict)
> $(UV) run pyright

check: lint typecheck test-all db-check obs-check ## Tout verifier avant d'ouvrir une PR

front-dev: ## Lance l'interface en local (http://localhost:5173), /api relaye vers localhost:8001
> cd frontend && pnpm dev

front-check: ## Frontend : lint, types, tests (parcours, accessibilite) et construction
> cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build

openapi: ## Regenere le contrat OpenAPI et le client TypeScript du frontend (apres un changement d'API)
> $(UV) run python scripts/export_openapi.py ../frontend/openapi.json
> cd frontend && pnpm api:generate

openapi-check: ## Echoue si frontend/openapi.json ne decrit plus l'API
> $(UV) run python scripts/export_openapi.py /tmp/lorakus-openapi.json
> diff -u frontend/openapi.json /tmp/lorakus-openapi.json || { echo "Contrat OpenAPI perime : lancer make openapi" >&2; exit 1; }

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

obs-up: up ## Ajoute Prometheus (9090), Alertmanager (9093), Grafana (3000) et node_exporter
> $(OBS) up -d --wait prometheus alertmanager grafana node-exporter

obs-check: ## Valide Prometheus (config, regles et leurs tests), Alertmanager et Grafana
> python3 -m json.tool infra/observability/grafana/dashboards/lorakus-api.json > /dev/null
> $(OBS) run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
> $(OBS) run --rm --no-deps --entrypoint promtool prometheus test rules /etc/prometheus/tests/lorakus_test.yml
> ./infra/observability/check-runbooks.sh
> $(OBS) run --rm --no-deps --entrypoint /bin/sh alertmanager -c 'sed -e "s|__DISCORD_OPS_WEBHOOK_URL__|https://discord.com/api/webhooks/1/test|" -e "s|__HEALTHCHECKS_PING_URL__|https://hc-ping.com/test|" /etc/alertmanager/alertmanager.yml.tmpl > /tmp/am.yml && amtool check-config /tmp/am.yml'

alert-test: ## Envoie une alerte de test sur Discord (pile d'observabilite lancee)
> ./infra/observability/alert-test.sh $(OBS)

backup-image: ## Construit l'image de sauvegarde (pg_dump, age, rclone)
> docker build -t $(BACKUP_IMAGE) infra/backup

backup: backup-image db-up ## Sauvegarde chiffree de la base vers B2
> $(COMPOSE) run --rm backup

restore-test: backup-image ## Restaure la derniere sauvegarde dans une base jetable et la verifie
> ./infra/backup/restore-test.sh

# ---------------------------------------------------------------- Circuit d'une modification
# Dell -> PR -> main -> serveur. Detail et exemples : DEVELOPMENT.md, section "Circuit".
LAST_DEPLOY_RUN = gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId'

pr: ## Applique un patch et ouvre la PR : make pr PATCH=chemin BRANCH=nom TITLE="type: titre"
> @test -n "$(PATCH)" -a -n "$(BRANCH)" -a -n "$(TITLE)" || { echo 'Usage : make pr PATCH=chemin BRANCH=nom TITLE="type: titre"'; exit 2; }
> git switch main && git pull --ff-only && git switch -c "$(BRANCH)" && git apply --index "$(PATCH)" && git commit -m "$(TITLE)" && git push -u origin HEAD && gh pr create --fill && echo "Attente du demarrage des verifications..." && sleep 20 && gh pr checks --watch

merge: ## Fusionne la PR de la branche courante dans main, puis revient sur main a jour
> gh pr merge --squash --delete-branch && git switch main && git pull --ff-only

deploy: ## Deploie main : attend les images, staging, puis approbation dans la page qui s'ouvre
> ./infra/deploy/wait-publish.sh
> gh workflow run deploy.yml -f action=deploy && sleep 5 && gh run view "$$($(LAST_DEPLOY_RUN))" --web && gh run watch "$$($(LAST_DEPLOY_RUN))" --exit-status

deploy-skip-staging: ## URGENCE seulement : deploie sans staging (a consigner)
> ./infra/deploy/wait-publish.sh
> gh workflow run deploy.yml -f action=deploy -f skip_staging=true && sleep 5 && gh run view "$$($(LAST_DEPLOY_RUN))" --web && gh run watch "$$($(LAST_DEPLOY_RUN))" --exit-status

rollback: ## Remet la version precedente en production (approbation requise)
> gh workflow run deploy.yml -f action=rollback && sleep 5 && gh run view "$$($(LAST_DEPLOY_RUN))" --web && gh run watch "$$($(LAST_DEPLOY_RUN))" --exit-status

prod-status: ## Affiche la version en service et la precedente (approbation requise)
> gh workflow run deploy.yml -f action=status && sleep 5 && gh run view "$$($(LAST_DEPLOY_RUN))" --web && gh run watch "$$($(LAST_DEPLOY_RUN))" --exit-status && gh run view "$$($(LAST_DEPLOY_RUN))" --log | grep -A5 -- '--- en service'

# ---------------------------------------------------------------- Versions (release-please)
# Lance depuis le Dell avec TON compte gh : la PR de version declenche donc la CI normalement
# (une PR creee par le jeton d'Actions ne la declencherait pas). Aucun jeton d'ecriture en CI.
RELEASE_PLEASE := npx --yes release-please@17.11.2
RELEASE_ARGS = --token="$$(gh auth token)" --repo-url=AnasKnanoua/lorakus --target-branch=main

release-pr: ## PR de version (CHANGELOG et numero) : make release-pr VERSION=0.2.0 (fin de phase)
> @test -n "$(VERSION)" || { echo 'Usage : make release-pr VERSION=0.2.0'; exit 2; }
> $(RELEASE_PLEASE) release-pr $(RELEASE_ARGS) --release-as="$(VERSION)" && sleep 20 && gh pr checks release-please--branches--main --watch

release: ## Apres fusion de la PR de version : cree le tag et la release GitHub
> git switch main && git pull --ff-only && $(RELEASE_PLEASE) github-release $(RELEASE_ARGS)
