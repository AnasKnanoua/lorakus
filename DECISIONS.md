# Décisions

Les décisions d'architecture sont consignées dans [`docs/adr/`](docs/adr). Statuts : **Validé** (par le propriétaire du projet), **Accepté** (tranché par délégation, réversible), **Proposé** (en attente d'avis), **Remplacé**.

## Index des ADR

| ADR | Titre | Statut | Revue prévue |
| --- | --- | --- | --- |
| [0001](docs/adr/0001-modular-monolith.md) | Monolithe modulaire | Validé | Si > 3 contributeurs ou besoin d'extraire un module |
| [0002](docs/adr/0002-backend-fastapi.md) | Backend FastAPI + SQLAlchemy 2 + Alembic | Accepté | Phase 6 |
| [0003](docs/adr/0003-postgresql-only.md) | PostgreSQL seul (relationnel, vecteurs, jobs, cache) | Accepté | > 10 utilisateurs ou > 1 M vecteurs |
| [0004](docs/adr/0004-job-queue.md) | File de jobs Procrastinate derrière le port `JobQueue` | Accepté (amendé 2026-11-08) | Si la maintenance du projet faiblit |
| [0005](docs/adr/0005-frontend.md) | Frontend SPA + PWA en React | Validé (2026-11-08) | — |
| [0006](docs/adr/0006-ai-abstraction.md) | Abstraction IA maison | Accepté | Phase 15 |
| [0007](docs/adr/0007-model-routing.md) | Routing par tâche, classe de données et licence ; embeddings locaux | Accepté (amendé 2026-11-08, 2026-11-12 (D-D) et 2026-11-13 (modèle d'embeddings)) | À chaque changement de tarif |
| [0008](docs/adr/0008-multi-tenancy-rls.md) | Multi-tenant dans les fondations (`user_id` + RLS) | Validé | Ouverture à d'autres utilisateurs |
| [0009](docs/adr/0009-compose-before-k3s.md) | Docker Compose avant k3s ; hébergement Always Free | Validé (D-A, 2026-11-08), hébergement amendé par 0036 | Changement d'hébergeur |
| [0010](docs/adr/0010-observability.md) | OpenTelemetry → Grafana LGTM self-hosted | Validé (exigence) / Accepté (outils) | Phase 6 (mesure RAM) |
| [0011](docs/adr/0011-migrations.md) | Migrations expand/contract, backup obligatoire | Validé (exigence) / Accepté (méthode) | — |
| [0012](docs/adr/0012-untrusted-content.md) | Contenu externe non fiable, outils à permissions | Accepté | Après chaque campagne red team |
| [0013](docs/adr/0013-lorakus-sensors.md) | App Android compagnon séparée (PWA + capteurs, lots HTTPS) | Validé (2026-11-08) | Phase 7 (deux apps ou une seule) |
| [0014](docs/adr/0014-context-intervention.md) | Context Engine et InterventionPolicy dans le Core | Accepté | Phase 11 |
| [0015](docs/adr/0015-data-provenance.md) | Provenance et contraintes de licence des données | Accepté | À chaque nouveau connecteur |
| [0016](docs/adr/0016-minimal-usage-collection.md) | Collecte d'usage numérique minimale | Accepté | Phase 11 |
| [0017](docs/adr/0017-motivation-curation.md) | Motivation = curation, pas un flux | Accepté | 2 mois après la phase 10 |
| [0018](docs/adr/0018-planning-in-core.md) | Tâches et agenda dans le Core (`planning`) | **Proposé** | Avant la phase 4 |
| [0019](docs/adr/0019-unified-signals.md) | Signaux unifiés, aucune notification directe | Accepté | — |
| [0020](docs/adr/0020-mvp-integrations.md) | Intégrations du MVP : ICS en lecture, Telegram, Web Push | Accepté | Phase 8 |
| [0021](docs/adr/0021-baseline-versions.md) | Socle de versions (Python 3.13, PostgreSQL 18) | Accepté | Tous les 12 mois |
| [0022](docs/adr/0022-public-repo-no-secrets.md) | Dépôt public, aucun secret dans le dépôt | Validé (D-B, 2026-11-08) | Avant toute ouverture commerciale |
| [0023](docs/adr/0023-codename-lorakus.md) | Nom de code LORAKUS | Validé (2026-11-08) | Avant toute ouverture commerciale |
| [0024](docs/adr/0024-blobstore-port.md) | Stockage de fichiers derrière le port `BlobStore` | Accepté | Passage à un hébergeur payant |
| [0025](docs/adr/0025-multi-agent-architecture.md) | Architecture multi-agents hiérarchique | Validé (D-H), amendé 2026-11-14 (routage en deux paliers) | Fin de la phase 3 |
| [0026](docs/adr/0026-specialist-contract.md) | Contrat des spécialistes, registre et orchestrateur | Validé (D-H), amendé 2026-11-14 (orchestrateur, cache par durée de vie, trace) | Fin de la phase 3 |
| [0027](docs/adr/0027-report-confidentiality.md) | Confidentialité des rapports transmis au LLM | Validé (D-I) | Après la phase 14 |
| [0028](docs/adr/0028-preparations-approvals.md) | Préparations en arrière-plan et file d'approbation | Accepté | Phase 6 |
| [0029](docs/adr/0029-progressive-friction.md) | Friction progressive et pactes volontaires (amende 0016) | Validé (D-J) | Phase 12 |
| [0030](docs/adr/0030-situation-engine.md) | Moteur de situations | Accepté | Phase 12 |
| [0031](docs/adr/0031-sentinel-push-probes.md) | Veilleur par sondes qui poussent leurs données | Accepté | Phase 17 |
| [0032](docs/adr/0032-chess-stockfish.md) | Analyste : Stockfish | Accepté | Avant toute distribution |
| [0033](docs/adr/0033-knowledge-graph-fsrs.md) | Archiviste : graphe PostgreSQL et FSRS | Accepté | Phase 16 |
| [0034](docs/adr/0034-python-only-backend.md) | Python seul côté serveur, Rust seulement sur mesure | Accepté | Si un profilage montre un goulot CPU |
| [0035](docs/adr/0035-notification-channels.md) | Canaux de notification : exploitation sur Discord, produit sur Telegram | Accepté | Ouverture à d'autres utilisateurs |
| [0036](docs/adr/0036-environments.md) | Environnements : production sur Oracle (amende 0009) ; staging et sentinelle remplacés par 0037 | Validé (2026-11-09), amendé par 0037 | Changement d'hébergeur |
| [0037](docs/adr/0037-ci-staging-external-sentinel.md) | Staging éphémère dans la CI, sentinelle externe par signal de vie (healthchecks.io) | Validé (2026-11-11) | Phase 17 ou disparition d'un service gratuit |
| [0038](docs/adr/0038-public-exposure-caddy.md) | Exposition publique par Caddy, limites par utilisateur dans l'application | Validé (2026-11-12) | Avant toute ouverture commerciale, ou API à plusieurs processus |
| [0039](docs/adr/0039-memory-v1.md) | Mémoire v1 : rien n'est retenu sans confirmation ; recherche hybride des souvenirs | Validé (2026-11-12, amendé 2026-11-13) | Avant toute ouverture commerciale |
| [0040](docs/adr/0040-chat-tools-confirmation-cards.md) | Outils dans le chat : le modèle demande, l'utilisateur confirme par une carte | Accepté (2026-11-14) | À chaque nouvel outil du chat ; avant toute ouverture commerciale |

## Décisions en attente d'avis

| Id | Question | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-E | Place du bien-être numérique | Collecte en phase 8, interventions en phase 12 | Phase 8 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | Phase 4 |

## Décisions prises

| Id | Décision | Date |
| --- | --- | --- |
| D-A | Oracle Always Free : `oracleworker` = production ; pas de k3s sur Oracle (staging : voir ADR 0036) | 2026-11-08 |
| D-B | Dépôt GitHub public ; aucun secret dans le dépôt, même chiffré | 2026-11-08 |
| D-C | Frontend React / TypeScript (ADR 0005 validé) | 2026-11-08 |
| D-H | Architecture multi-agents : profils de spécialiste sur les modules, orchestrateur au Core (ADR 0025, 0026) | 2026-11-08 |
| D-I | Confidentialité des rapports sensibles par marqueurs stricts (ADR 0027) | 2026-11-08 |
| D-J | Friction de niveau 3 uniquement par pactes préconfigurés (ADR 0029) | 2026-11-08 |
| D-K | Accès privé par réseau chiffré **non retenu** : l'API reste exposée publiquement, en vue d'une éventuelle commercialisation | 2026-11-08 |
| — | Architecture clients : PWA + app Android compagnon séparée (ADR 0013) | 2026-11-08 |
| — | Nom de code LORAKUS (ADR 0023) | 2026-11-08 |
| D-G | Domaine `lorakus.app` (Name.com) : `app.lorakus.app` (PWA et API à la même origine) et `staging.lorakus.app`, à partir de la phase 3. Name.com ne gère pas les enregistrements CAA : à ajouter si le DNS passe chez Cloudflare | 2026-11-09 |
| — | Environnements : production sur `oracleworker`, staging et sentinelle sur Azure for Students, pas de second compte Oracle (ADR 0036) | 2026-11-09 |
| — | Alertes d'exploitation sur Discord, notifications produit sur Telegram (ADR 0035) | 2026-11-09 |
| — | Pas de VM Azure : staging éphémère dans la CI, sentinelle healthchecks.io ; crédit Azure gardé (ADR 0037) | 2026-11-11 |
| — | Loki reporté en P3, avec les traces (amendement de l'ADR 0010) | 2026-11-11 |
| D-D | Budget IA : 10 $ prépayés sans rechargement automatique ; plafond applicatif de 3 $ par utilisateur et par mois ; Claude Haiku 5.5 seul fournisseur des conversations en phase 3 (amendement de l'ADR 0007) | 2026-11-12 |
| — | Exposition publique de `app.lorakus.app` à la PR 35 ; en production, la connexion du propriétaire exige la double authentification | 2026-11-12 |
| — | Exposition par Caddy (image `lorakus-web`), contrôle d'origine, limites par utilisateur dans PostgreSQL (API et appels IA), double authentification activée sur le serveur (ADR 0038) | 2026-11-12 |
| — | Mémoire v1 : rien n'est retenu sans confirmation, seuls les messages de l'utilisateur sont analysés, extrait vérifié mot pour mot, propositions activées par défaut (ADR 0039) | 2026-11-12 |
| — | Recherche hybride des souvenirs (plein texte français sans accents + vecteurs, fusion RRF, sans seuil absolu) ; prompt : identité, puis pertinence, puis récence ; évaluation avec le vrai modèle dans la CI (amendement de l'ADR 0039) | 2026-11-13 |
| — | Routage par le sens (PR 39) : objectif de 90 % non atteint avec le vrai modèle (0,833) ; marge 0 choisie sur le jeu de réglage, garde-fou de régression à 0,80 ; mots-clés d'abord en P4 | 2026-11-14 |
| — | Orchestrateur (PR 39) : palier 3 du routage et invalidation du cache par événements reportés à la P4 (amendements des ADR 0025 et 0026) ; trace « Pourquoi ? » enregistrée avec chaque réponse, souvenirs par identifiant | 2026-11-14 |
| — | Outils dans le chat (PR 38, ADR 0040) : cartes de confirmation écrites par le code, jamais confirmables par le modèle ; liste explicite des outils du chat ; un message = un appel dans la limite par minute ; une seule PR | 2026-11-13 |
| — | Hébergement et IA (recherche du 2026-11-13) : Oracle gratuit et Haiku 5.5 seul jusqu'à la v0.5 ; ARM payant, adaptateur IA européen et checklist RGPD seulement au premier client | 2026-11-13 |
| — | Embeddings locaux : `multilingual-e5-small` int8 par ONNX Runtime dans l'API, sans `fastembed`, fichiers intégrés à l'image et vérifiés par SHA-256 ; PR 37 en deux livraisons, socle mesuré (37a) puis recherche hybride (37b) (amendement de l'ADR 0007) | 2026-11-13 |

Sans réponse, la recommandation s'applique au début de la phase concernée et l'ADR passe en « Accepté ».
