# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : aucune (pré-v0.1.0)
- **Phase** : P1 — Fondations techniques : en production et exploitée ; restent le staging et la sentinelle externe
- **Dernière mise à jour** : 2026-11-10
- **Déploiement** : en production depuis le 2026-11-10 sur `oracleworker` (alias SSH `lorakus-prod`), par `deploy.yml` avec approbation ; commit `5b248ec` en service, `f08b8f9` en version précédente ; 6 services sains, 4 cibles Prometheus actives, sauvegarde quotidienne vers B2. Staging et sentinelle externe prévus sur Azure for Students (ADR 0036).
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
- PR Runbooks : `docs/runbooks/` (API, sauvegarde, disque, serveur, déploiement, restauration, pièges connus), lien vers le runbook dans chaque alerte Discord (vérifié en CI), `deploy.sh alert-test`, décision d'une clé B2 par machine.

## En cours

- VM Azure : création et durcissement, mesure de la mémoire réelle, puis sentinelle externe et staging léger.
- **Gel de la conception jusqu'à la v0.5** : nouvelles idées dans la section « Idées » de `ROADMAP.md`.

## Reste à faire en P1 (dans l'ordre)

1. Clés B2 par machine (`DEPLOYMENT.md` §7.2) : créer les deux clés, les installer, supprimer la clé partagée.
2. VM Azure (ADR 0036) : guide pas à pas, durcissement identique à `lorakus-prod`, mesure de la mémoire réelle.
3. Sentinelle externe : signal de vie poussé par la production (aucun port ouvert avant la P3), alerte Discord si elle disparaît, runbook « production disparue ».
4. Staging léger sur la même VM, déployé par le même `deploy.sh` ; y répéter la restauration complète (`docs/runbooks/restore.md`).
5. Décision Loki (P1 ou report en P3), puis clôture de la P1 et tag `v0.1.0`.

Ensuite : P2 (Core : identité, RLS, modules, registre des spécialistes).

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-D | Budget IA mensuel | 10 $ prépayés, plafond 5 $/mois | P3 |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |

## Décisions prises récemment

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
| Mémoire réelle de la VM Azure et pile de staging qu'elle peut porter | Création de la VM Azure |
| Restauration complète sur PostgreSQL 18 avec les conteneurs réels (étape SQL vérifiée sur PostgreSQL 16 seulement) | Mise en place du staging |
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
- La clé B2 est encore partagée entre le Dell et le serveur tant que l'étape 1 ci-dessus n'est pas faite.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
