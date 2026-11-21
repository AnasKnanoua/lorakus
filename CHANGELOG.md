# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versionnement : [SemVer](https://semver.org/lang/fr/). Depuis la v0.1.0, les nouvelles versions sont écrites par `release-please` à partir des titres de PR (Conventional Commits) : `make release-pr` puis `make release` (`DEVELOPMENT.md`). Les entrées antérieures ont été tenues à la main.

## [0.4.0](https://github.com/AnasKnanoua/lorakus/compare/v0.3.0...v0.4.0) (2026-11-21)


### Ajouté

* **academic:** courses and assessments that create their tasks (PR 46) ([#71](https://github.com/AnasKnanoua/lorakus/issues/71)) ([896c592](https://github.com/AnasKnanoua/lorakus/commit/896c592a73eee77107cae6aebe8f611cb6b7ea6f))
* **calendars:** ICS subscriptions with an SSRF-safe outbound client ([#69](https://github.com/AnasKnanoua/lorakus/issues/69)) ([0b95b90](https://github.com/AnasKnanoua/lorakus/commit/0b95b90dca7801500752d5035a3afdd2d0621b95))
* **core:** planning foundation with account timezone, tasks and agenda (PR 44) ([#67](https://github.com/AnasKnanoua/lorakus/issues/67)) ([e17cc9d](https://github.com/AnasKnanoua/lorakus/commit/e17cc9d5c78852781386d777fcd6fb5d9988476a))
* **focus:** Sergent v0 ([#77](https://github.com/AnasKnanoua/lorakus/issues/77)) ([bff7353](https://github.com/AnasKnanoua/lorakus/commit/bff7353ac44fe09ae001249f4263d60c68b60d50))
* **planning:** confirmed planning preferences ([#75](https://github.com/AnasKnanoua/lorakus/issues/75)) ([38cf6d3](https://github.com/AnasKnanoua/lorakus/commit/38cf6d37d60f80c4d676a7dcb4771ea2d2d4187f))
* **planning:** day planner and today page (PR 47) ([#74](https://github.com/AnasKnanoua/lorakus/issues/74)) ([8bb2af0](https://github.com/AnasKnanoua/lorakus/commit/8bb2af0dfeaa8c8d2793fe8761f8a7bdb51d75f4))
* **planning:** plan the day with Lorakus ([#76](https://github.com/AnasKnanoua/lorakus/issues/76)) ([671a4bd](https://github.com/AnasKnanoua/lorakus/commit/671a4bde3635ab23ef7f3c8a2dee8e4b3f45841b))
* **projects:** idea box, projects and project tasks ([#78](https://github.com/AnasKnanoua/lorakus/issues/78)) ([2da9d80](https://github.com/AnasKnanoua/lorakus/commit/2da9d801782360d07e6bb708210c9e09d21b1853))
* **ui:** polish chat reading, sidebar and tutoiement ([#70](https://github.com/AnasKnanoua/lorakus/issues/70)) ([3b68009](https://github.com/AnasKnanoua/lorakus/commit/3b6800945f67bb7c1842ada3c1f4797f47a6f282))


### Corrigé

* **academic:** ask before completing an assessment ([#72](https://github.com/AnasKnanoua/lorakus/issues/72)) ([e8acda3](https://github.com/AnasKnanoua/lorakus/commit/e8acda3f5d11b9f7d452858c26cb3dcb2cefc590))
* **assistant:** empty model reply is not an internal error ([#79](https://github.com/AnasKnanoua/lorakus/issues/79)) ([e711a92](https://github.com/AnasKnanoua/lorakus/commit/e711a92002bd7124a7087d156deccc19436f4829))
* **assistant:** never propose the same confirmation card twice ([#68](https://github.com/AnasKnanoua/lorakus/issues/68)) ([2263d0c](https://github.com/AnasKnanoua/lorakus/commit/2263d0c27cc5c5e2ba15d0065b44bee4301fb8bb))
* **deploy:** remove old images after each deploy ([#73](https://github.com/AnasKnanoua/lorakus/issues/73)) ([eecb00a](https://github.com/AnasKnanoua/lorakus/commit/eecb00a0cf8c037724191a600287534cdfb55a2d))


### Documentation

* validate planning in the core and plan phase 4 ([#66](https://github.com/AnasKnanoua/lorakus/issues/66)) ([bb7dfe9](https://github.com/AnasKnanoua/lorakus/commit/bb7dfe92306a22b7f4d674527b317099ba96e11a))

## [0.3.0](https://github.com/AnasKnanoua/lorakus/compare/v0.2.0...v0.3.0) (2026-11-18)


### Ajouté

* **assistant:** streaming conversations with fallback replies ([#34](https://github.com/AnasKnanoua/lorakus/issues/34)) ([1a3032b](https://github.com/AnasKnanoua/lorakus/commit/1a3032be4a1ca99511b3773436527bfda171b3e4))
* **assistant:** tools in chat with confirmation cards (PR 38) ([#56](https://github.com/AnasKnanoua/lorakus/issues/56)) ([68e88d8](https://github.com/AnasKnanoua/lorakus/commit/68e88d8666820ae067098c32b99d380adf4a4577))
* close phase 3 with injection corpus, model eval and my data page (PR 41) ([#61](https://github.com/AnasKnanoua/lorakus/issues/61)) ([fd715bb](https://github.com/AnasKnanoua/lorakus/commit/fd715bbb1ead5fe30f0a9434ede8e69cda159dfa))
* **core:** ai engine, model router and monthly budget ([#32](https://github.com/AnasKnanoua/lorakus/issues/32)) ([3517cea](https://github.com/AnasKnanoua/lorakus/commit/3517cea42bf623d8b100c83e4807cac7ee6b7ed9))
* **core:** hybrid search for memory facts (PR 37b) ([#54](https://github.com/AnasKnanoua/lorakus/issues/54)) ([9e50d53](https://github.com/AnasKnanoua/lorakus/commit/9e50d53119b6ae502f836a53ffb2080019709ae4))
* **core:** local embeddings for memory facts (PR 37a) ([#52](https://github.com/AnasKnanoua/lorakus/issues/52)) ([74ab239](https://github.com/AnasKnanoua/lorakus/commit/74ab23930fb459659ca9ab0319cd3f9cf0c8aec8))
* **core:** specialist orchestrator, intent routing and reply trace (PR 39) ([#57](https://github.com/AnasKnanoua/lorakus/issues/57)) ([4068114](https://github.com/AnasKnanoua/lorakus/commit/40681140c84fcea9264ecd0a32ac5b9a2d6c937e))
* **frontend:** design system, refined sidebar and memory page ([#50](https://github.com/AnasKnanoua/lorakus/issues/50)) ([ad0a031](https://github.com/AnasKnanoua/lorakus/commit/ad0a031038156a8f47a460a1467fb9c8d1451110))
* **frontend:** futuristic redesign with centered home composer ([#40](https://github.com/AnasKnanoua/lorakus/issues/40)) ([b1030b5](https://github.com/AnasKnanoua/lorakus/commit/b1030b5d656a4b2ffa3ce743b3b5ea531b182a51))
* **frontend:** installable chat app with streaming replies ([#35](https://github.com/AnasKnanoua/lorakus/issues/35)) ([29de054](https://github.com/AnasKnanoua/lorakus/commit/29de0543398f50fbcdb8683a842911b4c41708bf))
* **frontend:** scalable navigation, compact memory page and smooth transitions ([#48](https://github.com/AnasKnanoua/lorakus/issues/48)) ([b3996ec](https://github.com/AnasKnanoua/lorakus/commit/b3996ec9572e8ac0f6a211e9ede8b39a379ff331))
* **memory:** confirmed facts proposed from conversations ([#47](https://github.com/AnasKnanoua/lorakus/issues/47)) ([86b59e9](https://github.com/AnasKnanoua/lorakus/commit/86b59e9d2d4568702aeccc700c09b1d31f0d8bb3))
* **observability:** OpenTelemetry traces to Tempo and logs to Loki (PR 40) ([#58](https://github.com/AnasKnanoua/lorakus/issues/58)) ([7408762](https://github.com/AnasKnanoua/lorakus/commit/740876269cdf5dacc037a241f8611b523806c3fa))
* **web:** expose app.lorakus.app through caddy with origin check and per-user limits ([#41](https://github.com/AnasKnanoua/lorakus/issues/41)) ([7eb31a6](https://github.com/AnasKnanoua/lorakus/commit/7eb31a69b5f83fb06f63b13eaee036b59c26c642))


### Corrigé

* **api:** keep the release number out of the OpenAPI contract ([#65](https://github.com/AnasKnanoua/lorakus/issues/65)) ([662904f](https://github.com/AnasKnanoua/lorakus/commit/662904f6c997bcea0bd06f56c95790a8ed0019e2))
* **core:** disable ONNX Runtime telemetry, recalibrate memory limits ([#53](https://github.com/AnasKnanoua/lorakus/issues/53)) ([2de0c8a](https://github.com/AnasKnanoua/lorakus/commit/2de0c8a01ed43194056eafd84013bb25a03de302))
* **deploy:** handle redeploying the release already in production ([#55](https://github.com/AnasKnanoua/lorakus/issues/55)) ([38e37b9](https://github.com/AnasKnanoua/lorakus/commit/38e37b986035a7512341058441ed178a1692ff7d))
* **deploy:** keep the real previous release after a two-pass deployment ([#44](https://github.com/AnasKnanoua/lorakus/issues/44)) ([2f4dd84](https://github.com/AnasKnanoua/lorakus/commit/2f4dd84fc291efd79ddfe73a6611b1baf8662f79))
* **deploy:** reserve caddy address on the edge network ([#43](https://github.com/AnasKnanoua/lorakus/issues/43)) ([fb884e0](https://github.com/AnasKnanoua/lorakus/commit/fb884e0e1dac43a25b040c00e7e2a649f4676353))
* **deploy:** wait for the web image before deploying ([#49](https://github.com/AnasKnanoua/lorakus/issues/49)) ([14eaacc](https://github.com/AnasKnanoua/lorakus/commit/14eaaccf607935f67f32fc4ce197e87383864ac7))
* **frontend:** drawer swipe closes from the finger position ([#51](https://github.com/AnasKnanoua/lorakus/issues/51)) ([ef9f796](https://github.com/AnasKnanoua/lorakus/commit/ef9f796281ad60aa3f8c050ab79c3918c218af46))


### Documentation

* close phase 3 (v0.3.0) ([#63](https://github.com/AnasKnanoua/lorakus/issues/63)) ([00f0a43](https://github.com/AnasKnanoua/lorakus/commit/00f0a438f05966886f11518c4484bc43aa42c4b0))
* natural-language rules idea and accepted minimatch alert ([#46](https://github.com/AnasKnanoua/lorakus/issues/46)) ([89edae4](https://github.com/AnasKnanoua/lorakus/commit/89edae4a54ddc3486e9b7f35873a6077bed93bec))
* record PR 41 production measurements and model eval (PR 42) ([#62](https://github.com/AnasKnanoua/lorakus/issues/62)) ([20c2bab](https://github.com/AnasKnanoua/lorakus/commit/20c2bab6a44dc2dc7b15114d17dbe1240065681a))
* record public exposure in production ([#45](https://github.com/AnasKnanoua/lorakus/issues/45)) ([331c23e](https://github.com/AnasKnanoua/lorakus/commit/331c23e4da772cebd9d9bb260f9784dd9faafd6c))

## [0.2.0](https://github.com/AnasKnanoua/lorakus/compare/v0.1.0...v0.2.0) (2026-11-11)


### Ajouté

* **core:** core skeleton, architecture contracts and release-please ([#22](https://github.com/AnasKnanoua/lorakus/issues/22)) ([18deed2](https://github.com/AnasKnanoua/lorakus/commit/18deed2cc99c625deee8de71777e945ca170c8cb))
* **core:** events outbox, job queue and worker ([#29](https://github.com/AnasKnanoua/lorakus/issues/29)) ([4088c60](https://github.com/AnasKnanoua/lorakus/commit/4088c60f1b2a86f1888f0077cc0424b7db7c07ab))
* **core:** identity, sessions and row level security ([#23](https://github.com/AnasKnanoua/lorakus/issues/23)) ([5bc93d7](https://github.com/AnasKnanoua/lorakus/commit/5bc93d7cc043128372b0813baa7f9569149ac3f2))
* **core:** module system ([#27](https://github.com/AnasKnanoua/lorakus/issues/27)) ([f5cdf4a](https://github.com/AnasKnanoua/lorakus/commit/f5cdf4ac44315f04eaaf09dfd725ccb6bb7a7de7))
* **core:** second factor, api keys and audit log ([#25](https://github.com/AnasKnanoua/lorakus/issues/25)) ([b0cb705](https://github.com/AnasKnanoua/lorakus/commit/b0cb7059e8015c1017a61361feedd721750c4ce1))
* **core:** tools and specialists, close phase 2 ([#30](https://github.com/AnasKnanoua/lorakus/issues/30)) ([ca9e3c9](https://github.com/AnasKnanoua/lorakus/commit/ca9e3c9e8bca2220a1ae879b7fb354bccd7372c8))


### Corrigé

* **ops:** give the field encryption key to the api service ([#28](https://github.com/AnasKnanoua/lorakus/issues/28)) ([461d032](https://github.com/AnasKnanoua/lorakus/commit/461d032335590aac286f03fd25e0ebe6cb8b6ae2))
* **ops:** take the pre-migration backup with the new release image ([#24](https://github.com/AnasKnanoua/lorakus/issues/24)) ([a0b7ea7](https://github.com/AnasKnanoua/lorakus/commit/a0b7ea77387c29ba1b3fc70509f7abcbfff4a12f))

## [0.1.0] — 2026-11-11

Fin de la phase 1 : fondations techniques en production.

### Ajouté
- 2026-11-11 — `make pr` attend que GitHub démarre les vérifications avant de les suivre.
- 2026-11-11 — Vérifié en conditions réelles : staging éphémère vert sur runner ARM (dont restauration complète sur PostgreSQL 18) ; sentinelle : production déclarée disparue sur Discord 8 minutes après l'arrêt d'Alertmanager.
- 2026-11-11 — Staging éphémère (ADR 0037) : job `staging` de `deploy.yml` sur runner ARM, `infra/staging/staging-test.sh` (mise à jour depuis la version en production, retour arrière, sauvegarde, alerte de test, restauration vérifiée par une donnée témoin) ; un échec bloque la production. `infra/deploy/resolve-images.sh` partagé entre staging et production ; `deploy.sh compose` et fichier facultatif `compose.host.yml`.
- 2026-11-11 — Sentinelle externe : règle `LorakusWatchdog` toujours active, envoyée à healthchecks.io en production seulement ; `LorakusHeartbeatFailing` si l'envoi échoue ; runbook « production disparue » ; `HEALTHCHECKS_PING_URL` demandée par `init-env.sh`.
- 2026-11-11 — `make pr`, `make merge`, `make deploy`, `make rollback`, `make prod-status` ; circuit d'une modification dans `DEVELOPMENT.md`.
- 2026-11-11 — Idées : aide à l'apprentissage, mémorisation de sourates, emploi du temps, personnalité « professeur ».
- 2026-11-10 — Runbooks dans `docs/runbooks/` : API injoignable ou dégradée, sauvegarde en échec, disque plein, mémoire et métriques du serveur, déploiement en échec, restauration en production, pièges déjà rencontrés. Annotation `runbook_url` sur les 11 règles d'alerte, affichée dans le message Discord ; `make obs-check` refuse une règle sans runbook.
- 2026-11-10 — `deploy.sh alert-test` : alerte de test sur le serveur, avec l'environnement dans le titre.
- 2026-11-10 — Essais en production : retour arrière en 10 secondes, redéploiement en 26 secondes, alerte Discord 2 min 21 s après l'arrêt de l'API. Minuteur `lorakus-backup.timer` installé sur `lorakus-prod`.
- 2026-11-10 — Sauvegarde quotidienne de la production : `lorakus-backup.timer` et commande `deploy.sh backup` (attend la fin d'un déploiement). Label `environment` sur toutes les alertes, affiché dans le titre Discord.
- 2026-11-09 — Déploiement en production : workflow `deploy.yml` (approbation manuelle, empreinte SSH vérifiée, clé limitée à `deploy.sh`), `infra/deploy/deploy.sh` (sauvegarde avant migration, test de santé, retour automatique, `rollback`), `infra/deploy/init-env.sh` (secrets générés sur le serveur), `compose.prod.yml`.
- 2026-11-09 — Publication des images API et sauvegarde multi-architectures sur GHCR (`publish.yml`, `infra/ci/smoke-image.sh`).
- 2026-11-09 — ADR 0036 : production sur `oracleworker` (`lorakus-prod`), staging léger et sentinelle externe sur Azure for Students. Décision D-G tranchée : domaine `lorakus.app`. Questions de clarification ajoutées à la phase 4.
- 2026-11-08 — Décisions D-H, D-I, D-J validées ; D-K (accès privé) refusée. Revue « regard neuf » : MVP allégé (filtre de confidentialité et moteur de situations en P10, file d'approbation au premier besoin), observabilité par paliers, gel de la conception jusqu'à la v0.5, règles « pas de tâche planifiée par utilisateur » et « Telegram sans contenu sensible ».
- 2026-11-08 — Mission 3 : architecture multi-agents (Majordome et six spécialistes) proposée ; ADR 0025 à 0033 ; roadmap réordonnée (P1 à P17) ; décisions D-H, D-I, D-J ouvertes.
- 2026-11-08 — Nom de code LORAKUS (ADR 0023) ; architecture clients PWA + app Android compagnon séparée (ADR 0013 réécrit) ; décision D-G (adresse HTTPS) ouverte.
- 2026-11-08 — Décisions D-A (Always Free, prod + staging) et D-B (dépôt public) validées ; ADR 0022.
- 2026-11-08 — Mission 2 : architecture de référence consolidée, roadmap en 16 phases, définition du MVP v0.5, documentation initiale du dépôt, ADR 0001 à 0021.
- 2026-11-08 — Mission 1 : conception des modules `fitness`, `digital_activity`, `motivation`, du client Android LORAKUS Sensors et du Context Engine.
- 2026-11-08 — Mission 0 : dossier de conception initial (architecture, sécurité, IA, observabilité, infrastructure).

### Modifié
- 2026-11-10 — Une clé B2 par machine (`DEPLOYMENT.md` §7.2) : écriture sans suppression pour le serveur, lecture seule pour le poste de développement.
- 2026-11-10 — `deploy.sh` : `docker compose run` en `-T` sans entrée standard (migrations et sauvegardes), pour ne jamais consommer l'entrée d'un script appelant.
- 2026-11-10 — `deploy.sh` : Prometheus, Alertmanager et Grafana sont recréés à chaque mise en service, pour relire leur configuration même quand seuls leurs fichiers ont changé.
- 2026-11-09 — ADR 0009 amendé par 0036 ; `DEPLOYMENT.md`, `PROJECT_STATE.md`, `ROADMAP.md`, `SECURITY.md` et `ARCHITECTURE.md` alignés sur l'état réel (alertes sur Discord, secrets générés sur le serveur, sauvegardes B2).
- ADR 0005 validé (React) ; ADR 0014 complété par 0030 ; ADR 0016 amendé par 0029 sous réserve de la décision D-J ; module `digital_activity` renommé `focus`.
- ADR 0004 (port `JobQueue`), 0005 (framework frontend réouvert), 0007 (embeddings locaux, contraintes de licence) amendés.

### Corrigé
- 2026-11-10 — `make alert-test` : l'alerte de test porte maintenant le label `environment` (une alerte injectée par amtool ne passe pas par Prometheus) ; checklist de déploiement corrigée.

### Notes
- Aucune version publiée : le premier tag sera `v0.1.0` à la fin de la phase 1.
