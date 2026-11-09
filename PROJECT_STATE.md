# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : aucune (pré-v0.1.0)
- **Phase** : P1 — Fondations techniques (en cours)
- **Dernière mise à jour** : 2026-11-08
- **Déploiement** : rien de déployé. Production prévue sur `OracleWorker` ; staging sur une 2e instance A1.
- **Dépôt** : https://github.com/AnasKnanoua/lorakus

## Terminé

- Missions 0, 1, 2 : conception, extension sport / motivation / bien-être, référence consolidée.
- Mission 3 : architecture multi-agents (Majordome + six spécialistes) **validée**, ADR 0025 à 0033, roadmap 2.1 (P1 à P17), revue « regard neuf » (MVP allégé, observabilité par paliers).
- P0 : environnement, dépôt public protégé (ruleset, secret scanning, Dependabot), hooks pre-commit (Gitleaks, Ruff).
- P1, PR n°2 : backend FastAPI, `/api/health`, Ruff, pyright strict, Makefile.
- P1, PR n°3 : PostgreSQL 18 + pgvector local, image épinglée, rôles admin / migrator / app, `make db-check`.
- P1, PR n°4 : SQLAlchemy 2 async + psycopg 3, Alembic (branche `core`, migration 0001), `/api/health/ready`, tests anti-injection.

## En cours

- P1, PR n°14 : node_exporter (disque, mémoire, CPU) et métriques des sauvegardes (collecteur textfile), 7 nouvelles alertes testées (13 tests promtool), inhibition par composant, scan Trivy de l'image de sauvegarde.
- **Gel de la conception jusqu'à la v0.5** : nouvelles idées dans la section « Idées » de `ROADMAP.md`.

## Reste à faire en P1 (dans l'ordre)

1. ~~CI, Dependabot, CodeQL, image Docker, pile en conteneurs, journaux JSON et métriques, Prometheus et Grafana~~ (faits, PR n°7 à n°11).
2. Alertes vers Telegram (PR n°12, en cours).
3. Sauvegardes chiffrées hors Oracle et test de restauration automatisé.
4. Staging (2e instance A1) et premier déploiement sur `OracleWorker`.
5. Centralisation des journaux (Loki) : en dernier, ou reportée en P3 selon la mémoire disponible sur le VPS.

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-D | Budget IA mensuel | 10 $ prépayés, plafond 5 $/mois | P3 |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |
| D-G | Adresse HTTPS publique (l'API reste publique, D-K refusée) | Sous-domaine deSEC gratuit en attendant | Début P3 |

## Décisions prises récemment

- 2026-11-08 — D-H, D-I, D-J validées (architecture multi-agents, marqueurs de confidentialité, pactes).
- 2026-11-08 — D-K : accès privé par réseau chiffré **non retenu** ; l'API restera publique (commercialisation possible).
- 2026-11-08 — MVP allégé à environ 17,5 semaines : filtre de confidentialité et moteur de situations en P10, file d'approbation au premier besoin.
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
- Les versions de Gitleaks (8.30.1) et Trivy (0.76.1) sont figées dans `ci.yml` et ne sont pas suivies par Dependabot : les vérifier une fois par mois.
- Le DNS du réseau de METU redirige les domaines de téléchargement de Backblaze B2 vers un serveur de l'université (certificat `*.cc.metu.edu.tr`, refusé par rclone) : `make backup` et `make restore-test` ne fonctionnent pas depuis le campus. Utiliser le partage de connexion du téléphone, Wi-Fi du téléphone désactivé. Sans effet en production.
- La pile d'observabilité lancée sur le Dell envoie ses alertes dans le même salon Discord que la production : penser à `make down` après les tests. Un label d'environnement distinguera les deux au moment du déploiement.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
