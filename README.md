# LORAKUS

*Nom de code du projet anciennement appelé JARVIS (ADR 0023).*

Plateforme d'assistant personnel intelligent, modulaire et auto-hébergée : un assistant qui connaît votre situation (tâches, cours, agenda, mémoire), agit avec votre accord et prend l'initiative sans vous inonder de notifications.

> **Statut : phase 1 (fondations techniques), en production depuis le 2026-11-10.** Voir [`PROJECT_STATE.md`](PROJECT_STATE.md).

## Principes

- Monolithe modulaire : un seul déploiement, des modules qui ne se connaissent pas.
- Sécurité dès la conception : isolation par utilisateur (RLS), outils IA à permissions, contenu externe toujours traité comme non fiable.
- IA assistée, pas dépendante : calculs, règles et permissions sont déterministes ; le LLM comprend, formule et synthétise.
- Confidentialité : les données personnelles ne vont jamais vers une offre gratuite qui réutilise les données ; les données financières et de santé ne quittent jamais le serveur.
- Observabilité, migrations et sauvegardes testées dès la première version.

## Stack

| Couche | Choix |
| --- | --- |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Données | PostgreSQL 18 + pgvector (relationnel, vecteurs, file de jobs, cache) |
| Jobs | Procrastinate derrière le port `JobQueue` |
| IA | Port `AIProvider` maison : Claude (principal), Gemini (contenus publics), modèle local, `FakeProvider` |
| Frontend | SPA + PWA (framework : ADR-0005, **proposé** : React + Vite) |
| Clients | PWA (PC et navigateur Android), bot Telegram ; app Android compagnon Lorakus Sensors (Kotlin) et extension navigateur à partir de la phase 7 |
| Exploitation | Docker Compose, Caddy, GitHub Actions, GHCR |
| Observabilité | OpenTelemetry → Grafana Alloy → Loki, Prometheus, Tempo → Grafana ; Uptime Kuma |

## Démarrage rapide (disponible à partir de la phase 1)

```bash
git clone <dépôt> lorakus && cd lorakus
make bootstrap      # installe les dépendances (uv, pnpm) et les hooks pre-commit
make dev            # lance Postgres, API, worker, frontend et Grafana en local
make test           # tests unitaires et d'intégration
make lint           # Ruff, pyright, ESLint, import-linter
```

## Documentation

| Fichier | Contenu |
| --- | --- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architecture de référence, composants, flux, frontières de confiance |
| [`MODULE_SYSTEM.md`](MODULE_SYSTEM.md) | Contrat des modules, manifeste, ports, signaux, créer un module |
| [`SECURITY.md`](SECURITY.md) | Modèle de menace, classification des données, sécurité continue, incidents |
| [`ROADMAP.md`](ROADMAP.md) | Phases détaillées, MVP, critères de fin de phase |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Installation, conventions, tests, migrations |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Environnements, déploiement, rollback, sauvegardes, changement d'hébergeur |
| [`docs/runbooks/`](docs/runbooks/README.md) | Que faire quand une alerte tombe : pannes, sauvegardes, restauration, pièges connus |
| [`DECISIONS.md`](DECISIONS.md) | Index des ADR et décisions en attente |
| [`CHANGELOG.md`](CHANGELOG.md) | Historique des versions |
| [`PROJECT_STATE.md`](PROJECT_STATE.md) | Où en est le projet, à reprendre en premier |

## Licence

À définir (ADR à venir avant la publication du dépôt).
