# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS). Le nom affiché de l'assistant sera configurable.*

- **Version** : v0.3.0 (2026-11-18)
- **Phase** : P4 — Planning, academic, projects, Sergent v0, commencée le 2026-11-18 (D-F tranchée, découpage en PR 44 à 50 validé). P3 close le 2026-11-18 (v0.3.0).
- **Dernière mise à jour** : 2026-11-18
- **Déploiement** : en production depuis le 2026-11-10 sur `oracleworker` (alias SSH `lorakus-prod`), par `deploy.yml` avec approbation ; version en service : `make prod-status` ; services sains dont Caddy (`web`, ajouté aux cibles Prometheus), sauvegarde quotidienne vers B2. Seul Caddy est public (80 et 443). PR n°19 (runbooks) et n°20 (staging et sentinelle) déployées. Staging éphémère dans la CI avant chaque déploiement et sentinelle healthchecks.io (ADR 0037).
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
- P3, PR 32 à 42 (étape A, chemin le plus court vers une conversation : PR 32 à 35 ; étape B : PR 36 à 42) : moteur IA (`AIProvider`, adaptateur Anthropic, `ModelRouter`, refus structurels, plafond mensuel, disjoncteur, journal `core_ai_usage`) ; module `assistant` (conversations en SSE, prompt versionné, messages de secours) ; frontend React installable (identité « encre de nuit et aurore », système de design de `docs/frontend.md`, navigation déclarée dans `src/navigation.ts`) ; exposition publique sur `https://app.lorakus.app` par Caddy, limites par utilisateur, double authentification obligatoire (ADR 0038) ; mémoire v1, rien n'est retenu sans confirmation (ADR 0039) ; embeddings locaux `multilingual-e5-small` int8 dans l'API et recherche hybride (ADR 0007 amendé) ; outils dans le chat avec cartes de confirmation que le modèle ne peut pas confirmer (ADR 0040) ; orchestrateur des spécialistes et trace « Pourquoi ? » (ADR 0025 et 0026 amendés) ; traces vers Tempo et journaux vers Loki (ADR 0010 amendé) ; corpus de 31 injections à chaque CI, banc d'évaluation du vrai modèle (`model-eval.yml`), page « Mes données » (export et suppression des conversations), `docs/avant-premier-client.md`. Détail par PR, critères et mesures : `ROADMAP.md` (P3) et `CHANGELOG.md` ; mémoire des conteneurs : `DEPLOYMENT.md`.
- Mesures de clôture (production, 2026-11-18) : API 545 Mo sur 832, Tempo 233 sur 256 (dont 121 Mo `anon` : limite gardée), Loki 98 sur 256, Grafana 253 sur 512, Prometheus 122 sur 300, worker 80 sur 256 ; hôte 2,3 Go utilisés sur 5,6. IA : environ 0,28 millième de dollar et 1,6 s par appel (les 10 $ prépayés couvrent largement plus d'un an). Banc du vrai modèle (`claude-haiku-5-5`) : *security* 7/7, *quality* 7/7, 0,0051 $ ; recherche dans la mémoire recall@5 0,828 (objectif 0,85) et routage par le sens 0,833 (objectif 0,90) : objectifs non atteints, devenus des garde-fous de régression.
- Critères de fin de la P3 : question à trois spécialistes factices en moins de 5 s avec trace complète (PR 39) ; usage quotidien depuis le téléphone depuis le 2026-11-12, confirmé par le propriétaire le 2026-11-18.
- **Phase 3 close le 2026-11-18, version v0.3.0.**

## En cours (P4)

- Découpage validé le 2026-11-18 (`ROADMAP.md`, P4) : PR 44 (socle `planning`), 45 (`calendars`), 46 (`academic`), 47 (planificateur et Today), 48 (Sergent v0), 49 (`projects`), 50 (préférences et clôture).
- PR 44 — Socle `planning` (ADR 0018), **déployée le 2026-11-18** (migration 0013) ; essayée sur le téléphone (« Ajoute le devoir de CSEC507 pour le 23 nov » → carte « lundi 23 novembre 2026 (dans 5 jours) », confirmée). Bandeau du fuseau non affiché : diagnostic en cours (téléphone à l'heure de Paris, ancienne interface ouverte, ou fuseau déjà juste) :
  - **Fuseau du compte** (`core_account_settings`, `core/account/`) : seul fuseau pour « aujourd'hui » et l'heure donnée au modèle ; l'ancien réglage de l'assistant est recopié par la migration (vérifié en remontant de 0012 avec trois cas : valide, mal formé, absent). Route `GET /api/v1/account/settings` et `PUT /api/v1/account/timezone` ; bandeau qui propose le fuseau de l'appareil quand il diffère, jamais de changement sans clic, refus retenu par appareil. **Utile tout de suite** : jusqu'ici l'assistant croyait être à Paris, deux heures de moins qu'à Ankara.
  - **Tâches et agenda** : `core_tasks` (sous-tâches sur un niveau par une clé composée, module propriétaire, provenance, plafonds de 500 tâches ouvertes et 20 sous-tâches), `core_agenda_entries` (créneaux horaires en UTC ou journées entières, sans récurrence, idempotents par source et occurrence) ; contraintes écrites pour ne jamais valoir NULL (une CHECK à NULL passe : trouvé par les tests). Ports `ModuleTasks` et `ModuleAgenda` filtrés sur le module ; export dans « Mes données ».
  - **Chat** : outils `list_tasks`, `add_task`, `complete_task` (cartes) et `delete_task` (carte et preuve d'identité) ; date absolue sur la carte, date passée refusée avant toute carte, tâche d'un module non supprimable depuis le chat. Prompt `assistant-system-2026-11-18.2`. Corpus : les 31 attaques rejouées dans le titre d'une tâche ; banc : 4 cas de plus (18 au total, non encore mesurés avec le vrai modèle).
  - Vérifié localement (PostgreSQL 18) : voir le message de livraison ; mutations détectées (filtre du module sur les tâches et l'agenda, suppression d'une tâche de module, profondeur des sous-tâches, clôture des sous-tâches, plafond, validation des créneaux, chevauchement des jours, date passée, fuseau des outils et du prompt, risque des outils). Deux mutants équivalents notés : `day_bounds` calculé par `start + 1 jour` (l'arithmétique de Python sur une date avec fuseau suit déjà l'heure locale) et l'expression régulière du fuseau (ZoneInfo refuse déjà ces noms ; gardée pour coller à la contrainte de la base).
- **Correctif après la PR 44 — jamais deux fois la même carte** (2026-11-18, ADR 0040 amendé, *déploiement*) : bug vu en production (carte confirmée, ou laissée sans réponse, reproposée à chaque message). Une même action n'a qu'une confirmation en attente par conversation (`ToolRuntime`, `already_pending`) ; souvenir déjà connu ou proposé et tâche ouverte identique (titre sans casse, échéance) refusés avant toute carte ; note « faite, après confirmation de l'utilisateur » ; prompt `assistant-system-2026-11-18.3` ; banc : 2 cas (20 au total). 19 mutations détectées.
- Emploi du temps : pas d'ICS fourni par METU (capture d'écran reçue, créneaux de 50 minutes à HH:40) ; en attendant celui de TSP (2027), saisie des cours dans Google Agenda en événements récurrents, lus par l'adresse ICS secrète (PR 45).
- Reporté de la P3 : palier 3 du routage, invalidation du cache des spécialistes par événements, suppression des conversations par période ; amélioration du routage par le sens et de la recherche dans la mémoire (`ROADMAP.md`, « Idées »).

À faire quand c'est pratique, hors phase : clés B2 par machine (`DEPLOYMENT.md` §7.2).

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-E | Place du bien-être numérique | Collecte en P8, interventions en P12 | P8 |

## Décisions prises récemment

- 2026-11-18 — Correctif des cartes reproposées avant la PR 45 : une règle qui protège l'utilisateur ne tient jamais par le seul prompt ; le code la garantit et un faux modèle qui fait l'inverse la teste (`docs/runbooks/pitfalls.md`).
- 2026-11-18 — D-F : `planning` dans le Core (ADR 0018 validé et amendé) ; découpage de la P4 validé ; inspirations d'OpenJarvis triées (fuseau horaire et protection SSRF dans la P4, le reste dans « Idées »).
- 2026-11-18 — Clôture de la P3 et v0.3.0 après confirmation de l'usage quotidien par le propriétaire.
- 2026-11-18 — Mémoire d'un conteneur qui écrit sur disque (Tempo, Loki, Prometheus) : décider d'une limite d'après `anon` dans `memory.stat`, pas d'après `docker stats` seul, qui compte aussi du cache de fichiers récupérable ; Tempo garde 256 Mo (121 Mo `anon` mesurés). Consommation IA réelle : environ 0,28 millième de dollar et 1,6 s par appel ; les 10 $ prépayés couvrent largement plus d'un an d'usage personnel.
- 2026-11-18 — PR 41 : corpus d'injections et évaluation du modèle en pytest, sans Promptfoo (dépendances Node nombreuses, télémétrie par défaut) ; blocs de données rendus inertes par `inert()` ; export « Mes données » par un `data_exporter` optionnel du manifeste ; API à 832 Mo et alerte à 700 Mo (mesures du 2026-11-14) ; checklist `docs/avant-premier-client.md`.
- 2026-11-13 — PR 38 en une seule PR (ADR 0040) ; règle « un message = un appel par minute » ; noms des outils préfixés par le module (`assistant.search_memory`…).
- 2026-11-13 — Recherche hébergement et IA : Oracle gratuit et Haiku 5.5 seul jusqu'à la v0.5 (consommation réelle : environ 0,0002 $ par message) ; ARM payant, adaptateur IA européen et checklist RGPD au premier client seulement. Lorakus reste à usage personnel.
- 2026-11-13 — Mesures du modèle d'embeddings en production : limite de l'API gardée à 768 Mo, alerte à 650 Mo, Grafana à 512 Mo ; télémétrie d'ONNX Runtime coupée.
- 2026-11-13 — Embeddings locaux (amendement de l'ADR 0007) : `multilingual-e5-small` int8 par ONNX Runtime, sans `fastembed` ; PR 37 en deux livraisons (37a socle mesuré, 37b recherche hybride). Idées notées : capture rapide des notes (« Partager → Lorakus »), suggestions d'idées sur les créneaux libres, cartes de rappel sur l'accueil.
- 2026-11-12 — ADR 0038 : exposition par Caddy, limites par utilisateur dans l'application (API et appels IA), double authentification activée sur le serveur ; pas de limite par IP dans Caddy (module tiers). Idées notées : contrôle du téléphone en deux niveaux, prénom de l'utilisateur, nom de l'assistant au choix du client, revue de sécurité complète avant toute vente.
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
| Qualité du routage d'intention sans LLM (règles + embeddings locaux) : 0,833 mesuré pour 0,90 visé | P4 (mots-clés du Sergent, puis classifieur ou palier 3) |
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
