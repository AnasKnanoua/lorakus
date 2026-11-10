# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : aucune (pré-v0.1.0)
- **Phase** : P1 — Fondations techniques : publication faite, déploiement en cours
- **Dernière mise à jour** : 2026-11-09
- **Déploiement** : outillé (`deploy.yml`, `infra/deploy/`), premier déploiement à faire. Hôte de production `oracleworker` (alias SSH `lorakus-prod`) préparé ; images arm64 vérifiées dessus. Staging et sentinelle externe prévus sur Azure for Students (ADR 0036).
- **Dépôt** : https://github.com/AnasKnanoua/lorakus

## Terminé

- Missions 0 à 3 : conception, architecture multi-agents validée (ADR 0025 à 0033), roadmap P1 à P17, MVP allégé.
- P0 : environnement, dépôt public protégé, hooks pre-commit.
- P1, PR n°2 à n°4 : backend FastAPI, PostgreSQL 18 avec rôles à moindre privilège, SQLAlchemy 2 async, Alembic, `/api/health/ready`.
- P1, PR n°7 à n°10 : CI obligatoire (checks, secrets, titre de PR, image), CodeQL, Dependabot (délai de 14 jours), Gitleaks et Trivy épinglés, image API non-root multi-étapes, pile Compose durcie (lecture seule, `cap_drop: ALL`, `no-new-privileges`, un secret par service), journaux JSON avec `request_id`, métriques Prometheus.
- P1, PR n°11 à n°14 : Prometheus, Grafana, Alertmanager vers Discord (ADR 0035), node_exporter, 11 règles d'alerte testées (13 tests promtool), sauvegardes chiffrées `age` vers Backblaze B2 (clé sans droit de suppression), `make restore-test`, métriques de sauvegarde.
- Hôte de production préparé : mises à jour de sécurité automatiques, Docker, utilisateur `deploy`, SSH par clé uniquement, pare-feu limité à SSH, liste de sécurité Oracle nettoyée, nom d'hôte persistant (`DEPLOYMENT.md` §2.1).
- Domaine `lorakus.app` enregistré (D-G).
- PR n°15 : ADR 0036 (environnements), documentation alignée.
- PR n°16 : images API et sauvegarde multi-architectures, construites nativement, testées et analysées, publiées publiquement sur GHCR (`publish.yml`).

## En cours

- PR Déploiement : `deploy.yml` (approbation manuelle), `infra/deploy/deploy.sh` (sauvegarde, migrations, test de santé, retour automatique), `infra/deploy/init-env.sh` (secrets générés sur le serveur), `compose.prod.yml`.
- **Gel de la conception jusqu'à la v0.5** : nouvelles idées dans la section « Idées » de `ROADMAP.md`.

## Reste à faire en P1 (dans l'ordre)

1. PR Déploiement : en cours (voir ci-dessus), puis premier déploiement et essai du retour arrière.
2. PR Exploitation : minuteur systemd de sauvegarde quotidienne, label d'environnement dans les alertes, VM Azure en staging et sentinelle.
3. Centralisation des journaux (Loki) : en dernier, ou reportée en P3 selon la mémoire disponible.

Ensuite : P2 (Core : identité, RLS, modules, registre des spécialistes).

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-D | Budget IA mensuel | 10 $ prépayés, plafond 5 $/mois | P3 |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |

## Décisions prises récemment

- 2026-11-09 — ADR 0036 : production sur `oracleworker`, staging léger et sentinelle externe sur Azure for Students (non critique, usage non commercial, alerte de budget à 5 $) ; pas de second compte Oracle.
- 2026-11-09 — D-G : domaine `lorakus.app` ; `app.lorakus.app` et `staging.lorakus.app` à partir de la phase 3 ; aucune exposition publique avant.
- 2026-11-09 — ADR 0035 : alertes d'exploitation sur Discord, notifications produit sur Telegram.
- 2026-11-09 — Questions de clarification ajoutées à la phase 4.
- 2026-11-08 — D-H, D-I, D-J validées ; D-K (accès privé) non retenue ; MVP allégé ; frontend React / TypeScript ; D-A, D-B ; nom de code LORAKUS ; PWA et app Android compagnon.

## Hypothèses à vérifier

| Hypothèse | Avant |
| --- | --- |
| Mémoire réelle de la VM Azure et pile de staging qu'elle peut porter | PR Exploitation |
| Santé de Procrastinate | P2 |
| Qualité du routage d'intention sans LLM (règles + embeddings locaux) | P3 |
| Quota réel du free tier Gemini | P9 |
| Rétention des événements UsageStats sur One UI ; WorkManager face à l'optimisation batterie | P8 |
| Mi Fitness et Strava écrivent-ils les séances dans Health Connect ? API Strava gratuite ? | P10 |
| Temps d'analyse Stockfish acceptable sur 1 OCPU | P13 |
| Licence GPL de `python-chess` et Stockfish compatible avec une éventuelle distribution | Avant toute distribution |
| Azure for Students : usage non commercial, à quitter avant toute vente | Avant toute ouverture commerciale |

## Problèmes connus

- Quota Oracle Always Free réduit en juin 2026 ; aucune marge pour un serveur gratuit supplémentaire.
- `httpx` déprécié par Starlette au profit de `httpx2` : à prendre en compte pour le client HTTP des connecteurs.
- Les versions de Gitleaks (8.30.1) et Trivy (0.76.1) sont figées dans `ci.yml` et ne sont pas suivies par Dependabot : les vérifier une fois par mois.
- Le DNS du réseau de METU redirige les domaines de téléchargement de Backblaze B2 : `make backup` et `make restore-test` ne fonctionnent pas depuis le campus. Utiliser le partage de connexion du téléphone, Wi-Fi du téléphone désactivé. Sans effet en production.
- La pile d'observabilité lancée sur le Dell alerte dans le même salon Discord que la production : `make down` après les tests, jusqu'à l'ajout du label d'environnement (PR Exploitation).
- FastAPI 0.162 n'aplatit plus `include_router` : le modèle de route des métriques est reconstitué à partir de `scope["route"]` (fait et testé) ; à surveiller lors des montées de version.
- Name.com ne gère pas les enregistrements CAA : à ajouter si le DNS passe chez Cloudflare.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
