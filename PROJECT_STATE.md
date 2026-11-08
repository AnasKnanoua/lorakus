# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : aucune (pré-v0.1.0)
- **Phase** : P1 — Fondations techniques (en cours)
- **Dernière mise à jour** : 2026-11-08
- **Déploiement** : rien de déployé. Production prévue sur `OracleWorker` ; staging sur une 2e instance A1.
- **Dépôt** : https://github.com/AnasKnanoua/lorakus

## Terminé

- Missions 0, 1, 2 : conception, extension sport / motivation / bien-être, référence consolidée.
- Mission 3 : architecture multi-agents (Majordome + six spécialistes) **proposée**, ADR 0025 à 0033, roadmap 2.0 (P1 à P17).
- P0 : environnement, dépôt public protégé (ruleset, secret scanning, Dependabot), hooks pre-commit (Gitleaks, Ruff).
- P1, PR n°2 : backend FastAPI, `/api/health`, Ruff, pyright strict, Makefile.
- P1, PR n°3 : PostgreSQL 18 + pgvector local, image épinglée, rôles admin / migrator / app, `make db-check`.
- P1, PR n°4 : SQLAlchemy 2 async + psycopg 3, Alembic (branche `core`, migration 0001), `/api/health/ready`, tests anti-injection.

## En cours

- Documentation Mission 3 (cette PR).

## Reste à faire en P1 (dans l'ordre)

1. CI GitHub Actions : `make check` avec PostgreSQL de service, vérification du titre de PR, puis règle « CI verte obligatoire » sur `main`.
2. `dependabot.yml` et CodeQL ; corriger `compose.yml` en `pgvector/pgvector:pg18@sha256:…` (tag + empreinte).
3. Image Docker de l'API (multi-arch, non-root) et Compose de production.
4. Observabilité : structlog, OpenTelemetry, Grafana (Alloy, Loki, Prometheus, Tempo).
5. Sauvegardes chiffrées hors Oracle et test de restauration.
6. Staging (2e instance A1, guide pas à pas) et premier déploiement sur `OracleWorker`.

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-D | Budget IA mensuel | 10 $ prépayés, plafond 5 $/mois | P3 |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |
| D-G | Adresse HTTPS publique | Sous-domaine deSEC gratuit en attendant | Début P3 |
| D-H | Architecture multi-agents (ADR 0025, 0026) | Profils de spécialiste sur les modules, orchestrateur au Core | P2 |
| D-I | Confidentialité des rapports sensibles (ADR 0027) | Marqueurs stricts par défaut | P3 |
| D-J | Friction de niveau 3 par pactes (ADR 0029) | Autoriser, uniquement par pactes préconfigurés | P12 |

## Décisions prises récemment

- 2026-11-08 — Frontend React / TypeScript (ADR 0005 validé).
- 2026-11-08 — Veilleur placé en premier après le MVP ; sondes en lecture seule, aucun accès SSH par Lorakus (ADR 0031).
- 2026-11-08 — Module `digital_activity` renommé `focus` (porte le Sergent).
- 2026-11-08 — D-A : Oracle Always Free ; D-B : dépôt public sans secret ; nom de code LORAKUS ; PWA + app Android compagnon.

## Hypothèses à vérifier

| Hypothèse | Avant |
| --- | --- |
| Instance A1 existante en plus d'`OracleWorker` (ex. `anime-notif-worker`) : réutiliser ou supprimer | Fin de P1 |
| Santé de Procrastinate | P2 |
| Qualité du routage d'intention sans LLM (règles + embeddings locaux) | P3 |
| Quota réel du free tier Gemini | P9 |
| Rétention des événements UsageStats sur One UI ; WorkManager face à l'optimisation batterie | P8 |
| Mi Fitness et Strava écrivent-ils les séances dans Health Connect ? API Strava gratuite ? | P10 |
| Temps d'analyse Stockfish acceptable sur 1 OCPU | P13 |
| Licence GPL de `python-chess` et Stockfish compatible avec une éventuelle distribution | Avant toute distribution |

## Problèmes connus

- Quota Oracle Always Free réduit en juin 2026 ; aucune marge pour un 3e serveur gratuit.
- `httpx` déprécié par Starlette au profit de `httpx2` : à prendre en compte pour le client HTTP des connecteurs.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
