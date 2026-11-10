# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versionnement : [SemVer](https://semver.org/lang/fr/). À partir de la phase 1, ce fichier est généré par `release-please` à partir des Conventional Commits.

## [Non publié]

### Ajouté
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
