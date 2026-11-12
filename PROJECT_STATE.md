# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : v0.2.0 (2026-11-12)
- **Phase** : P3 — Majordome, IA et mémoire, en cours depuis le 2026-11-12 (premier usage visible : discuter avec Lorakus depuis le téléphone)
- **Dernière mise à jour** : 2026-11-12
- **Déploiement** : en production depuis le 2026-11-10 sur `oracleworker` (alias SSH `lorakus-prod`), par `deploy.yml` avec approbation ; version en service : `make prod-status` ; 6 services sains, 4 cibles Prometheus actives, sauvegarde quotidienne vers B2. PR n°19 (runbooks) et n°20 (staging et sentinelle) déployées. Staging éphémère dans la CI avant chaque déploiement et sentinelle healthchecks.io (ADR 0037).
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
- PR n°17 : déploiement (`deploy.yml` avec approbation, `deploy.sh` avec retour automatique, secrets générés sur le serveur, clé GitHub limitée à `deploy.sh`). Premier déploiement le 2026-11-10.
- PR n°18 (Exploitation), déployée le 2026-11-10 : sauvegarde quotidienne (`lorakus-backup.timer` installé et vérifié sur `lorakus-prod`, `deploy.sh backup`), label `environment` dans toutes les alertes.
- Essais en production le 2026-11-10 : retour arrière en 10 secondes, puis redéploiement complet en 26 secondes ; API coupée → alerte Discord « [production] Critique — LorakusApiDown » en 2 min 21 s, puis résolution.
- PR n°19 (Runbooks) : `docs/runbooks/` (API, sauvegarde, disque, serveur, déploiement, restauration, pièges connus), lien vers le runbook dans chaque alerte Discord (vérifié en CI), `deploy.sh alert-test`, décision d'une clé B2 par machine.
- PR n°20 (Staging et sentinelle, ADR 0037), déployée le 2026-11-11 : premier passage réel du staging vert sur runner ARM (mise à jour, retour arrière, sauvegarde, restauration complète sur PostgreSQL 18) ; disparition simulée (Alertmanager arrêté) → message healthchecks.io « DOWN » sur Discord en 8 minutes ; raccourcis `make pr`, `make merge`, `make deploy`.
- **Phase 1 close le 2026-11-11, version v0.1.0.**
- P2, PR 22 à 31 : squelette du Core et `release-please`, identité et RLS forcée, double authentification, clés d'API, journal d'audit, système de modules, événements (outbox), jobs (Procrastinate) et service `worker`, outils et spécialistes ; correctifs PR 24 et 28. Détail dans `ROADMAP.md` (P2) et `CHANGELOG.md`.
- **Phase 2 close le 2026-11-12, version v0.2.0.**

## En cours (P3)

- Refonte de l'interface (2026-11-12, avant la PR 35) : identité « encre de nuit et aurore » (accent jade, orbe, police Inter, contrastes calculés), accueil avec la question et le champ au centre, glissement du champ vers le bas au premier envoi, champ flottant sans ligne de séparation, réponses sans bulle avec « Copier », blocs de code avec en-tête, barre latérale repliable, tutoiement (y compris les messages de secours), nouvelle icône. Rendu vérifié dans un vrai navigateur, ordinateur et téléphone, thèmes sombre et clair. Défauts corrigés grâce aux captures : écran d'activation retardé par les nouvelles tentatives, clignotement de l'accueil, message affiché deux fois pendant l'écriture. Idées notées : bibliothèque de demandes préparées, mode vocal plein écran « cinématique ».
- PR 34 — Frontend : application installable (React, TypeScript strict, Vite, TanStack, Tailwind), connexion avec double authentification, conversations en flux, suppression, activation du module, thèmes clair et sombre, design system aux contrastes calculés (`docs/frontend.md`) ; client généré depuis l'OpenAPI (contrat vérifié en CI) ; job CI `frontend`. Corrections d'exploitation : `init-env.sh` refuse root et tout autre utilisateur que le propriétaire de `.env` (il avait rendu `.env` illisible pour `deploy`) ; `docker push` retenté trois fois (erreur `unknown blob` de GHCR). Utilisable sur le téléphone après la PR 35.
- PR 33 — Module `assistant` : conversations et messages (RLS forcée, clé étrangère composée), réponse en SSE enregistrée même si le client part, historique borné, prompt système versionné, messages de secours (plafond, panne, coupure, erreur), cinq alertes IA avec runbook (`docs/runbooks/ai.md`), clé Anthropic au seul service `api` (saisie par `init-env.sh`). Correctifs trouvés en chemin : l'image n'embarquait pas les migrations des modules (Alembic les aurait ignorées en silence) et pyright strict ne couvrait pas `lorakus_modules`.
- Correctif CI (2026-11-12) : analyse des secrets des images séparée de celle des vulnérabilités et bloquante dès HIGH (une clé privée embarquée n'était signalée qu'en HIGH, donc non bloquante).
- Découpage en PR 32 à 41 et critères validés le 2026-11-12 (`ROADMAP.md`, P3). Étape A, chemin le plus court vers une conversation : PR 32 (moteur IA), 33 (module `assistant`), 34 (frontend), 35 (exposition sur `app.lorakus.app`).
- PR 32 — Moteur IA : port `AIProvider`, adaptateur Anthropic (SDK 2.3.0), `FakeProvider` (développement et tests seulement), `ModelRouter` avec `routing.toml` et `pricing.toml`, refus structurels (`no_ai`, `sensitive` vers l'extérieur, prompt trop long, `LORAKUS_AI_KILL_SWITCH`), plafond mensuel par utilisateur, disjoncteur, journal `core_ai_usage` (migration 0007, RLS forcée, ajout seul), six métriques `lorakus_ai_*`. Aucun déploiement nécessaire : sans clé, la production n'a aucun fournisseur actif ; la migration partira avec la PR 33.

À faire quand c'est pratique, hors phase : clés B2 par machine (`DEPLOYMENT.md` §7.2).

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |

## Décisions prises récemment

- 2026-11-12 — D-D : 10 $ prépayés chez Anthropic sans rechargement automatique, plafond applicatif de 3 $ par utilisateur et par mois ; Claude Haiku 5.5 seul fournisseur des conversations en P3 ; repli par gabarit (amendement de l'ADR 0007). Prix vérifiés le jour même.
- 2026-11-12 — Découpage de la P3 (PR 32 à 41) ; ouverture publique de `app.lorakus.app` à la PR 35, double authentification obligatoire pour se connecter en production.
- 2026-11-12 — Mémoire mesurée sur `lorakus-prod` avec le worker : 1,7 Go utilisés sur 5,6 Go, worker 64 Mo (limite 256), Grafana 247 Mo (limite portée de 256 à 384).
- 2026-11-12 — PR 30 et 31 regroupées pour clore la P2 plus vite ; la P3 commence par l'écran de conversation.

- 2026-11-11 — P2 : pas d'inscription publique (propriétaire créé par une commande sur le serveur), pas d'interface (API et tests seulement) ; critères de sécurité par PR dans `ROADMAP.md`.
- 2026-11-11 — `release-please` lancé depuis le poste avec le compte `gh` (aucun jeton d'écriture en CI) ; version lue dans `backend/lorakus/__init__.py` pour que `uv.lock` ne change pas à chaque version.
- 2026-11-11 — P1 close, v0.1.0 ; vérifié : staging réel vert (restauration PostgreSQL 18 comprise), sentinelle en 8 minutes.
- 2026-11-11 — ADR 0037 : pas de VM Azure (tailles gratuites bloquées dans les régions autorisées) ; staging éphémère dans la CI avant chaque déploiement ; sentinelle healthchecks.io alimentée par une alerte toujours active ; crédit Azure (90 $, jusqu'au 09/11/2027) conservé.
- 2026-11-11 — Loki reporté en P3, avec Tempo (amendement de l'ADR 0010).
- 2026-11-10 — Une clé B2 par machine : écriture sans suppression pour le serveur, lecture seule pour le Dell (`DEPLOYMENT.md` §7.2).
- 2026-11-10 — Chaque alerte porte un lien vers son runbook ; une règle sans runbook fait échouer la CI.
- 2026-11-10 — Images de production épinglées par empreinte ; mémoire de l'hôte : environ 1,3 Go utilisés sur 5,6 Go, Loki envisageable en P1.
- 2026-11-09 — ADR 0036 : production sur `oracleworker`, staging léger et sentinelle externe sur Azure for Students (non critique, usage non commercial, alerte de budget à 5 $) ; pas de second compte Oracle.
- 2026-11-09 — D-G : domaine `lorakus.app` ; `app.lorakus.app` et `staging.lorakus.app` à partir de la phase 3 ; aucune exposition publique avant.
- 2026-11-09 — ADR 0035 : alertes d'exploitation sur Discord, notifications produit sur Telegram.
- 2026-11-09 — Questions de clarification ajoutées à la phase 4.
- 2026-11-08 — D-H, D-I, D-J validées ; D-K (accès privé) non retenue ; MVP allégé ; frontend React / TypeScript ; D-A, D-B ; nom de code LORAKUS ; PWA et app Android compagnon.

## Hypothèses à vérifier

| Hypothèse | Avant |
| --- | --- |
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
- La pile d'observabilité lancée sur le Dell alerte dans le même salon Discord que la production ; ses alertes portent `[development]` dans le titre. `make down` après les tests reste conseillé.
- FastAPI 0.162 n'aplatit plus `include_router` : le modèle de route des métriques est reconstitué à partir de `scope["route"]` (fait et testé) ; à surveiller lors des montées de version.
- Name.com ne gère pas les enregistrements CAA : à ajouter si le DNS passe chez Cloudflare.
- `deploy.sh` ne supprime pas les anciennes images Docker : elles s'accumulent à chaque déploiement (nettoyage manuel dans `docs/runbooks/disk-full.md`, automatisation à prévoir si le disque le demande).
- Exception Trivy pour le SDK Anthropic : `infra/ci/trivy-secret.yaml`, à revoir à chaque mise à jour du SDK (`docs/runbooks/pitfalls.md`).
- La clé B2 est encore partagée entre le Dell et le serveur tant que l'étape 1 ci-dessus n'est pas faite.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
