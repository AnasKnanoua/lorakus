# État du projet LORAKUS

*Nom de code depuis le 2026-11-08 (anciennement JARVIS).*

- **Version** : aucune (pré-v0.1.0)
- **Phase** : P1 — Fondations techniques (en cours)
- **Dernière mise à jour** : 2026-11-08
- **Déploiement** : rien de déployé. Production prévue sur `OracleWorker` ; staging sur une 2e instance A1 (à préparer en fin de P1).

## Terminé

- Mission 0 — dossier de conception initial.
- Mission 1 — extension Sport, Motivation, Digital Wellbeing.
- Mission 2 — architecture de référence consolidée, MVP v0.5, roadmap P0–P16, documentation initiale, ADR 0001–0021.

## En cours

- P1, PR n°3 : PostgreSQL 18 + pgvector en local (Compose), rôles admin / migrator / app, vérification automatique des permissions.

## Décisions en attente (voir `DECISIONS.md`)

| Id | Sujet | Recommandation | Bloque |
| --- | --- | --- | --- |
| D-C | Framework frontend (ADR 0005) | React SPA | P3 |
| D-D | Budget IA mensuel | 10 $ prépayés, plafond 5 $/mois | P3 |
| D-E | Place du bien-être numérique | Collecte P7, interventions P11 | P7 |
| D-F | `planning` dans le Core (ADR 0018) | Oui | P4 |
| D-G | Adresse HTTPS publique (domaine acheté ou deSEC gratuit) | deSEC en attendant | Début P3 |

## Décisions prises récemment

- 2026-11-08 — D-A : Oracle Always Free, prod sur `OracleWorker`, staging sur une 2e instance A1, pas de k3s sur Oracle.
- 2026-11-08 — D-B : dépôt public, aucun secret dans le dépôt (ADR 0022).
- 2026-11-08 — Nom de code LORAKUS (ADR 0023).
- 2026-11-08 — Clients : PWA + app Android compagnon séparée, lots HTTPS, pas de WebSocket (ADR 0013).
- 2026-11-08 — Pas d'achat de domaine pour l'instant ; développement local jusqu'à la fin de P2.

## Prochaines étapes (dans l'ordre)

1. ~~Correctif CVE-2026-98432 sur `OracleWorker`~~ (fait).
2. ~~Vérifier l'exposition du Dell~~ (fait).
3. ~~Installer les outils de développement~~ (fait : uv 0.13, Python 3.13.16, Node 26, pnpm 12, Docker 29, gh, pre-commit, Gitleaks, age).
4. Domaine : reporté (D-G, début P3).
5. ~~Créer le dépôt public~~ (fait : ruleset `protect-main`, protection des secrets au push, Dependabot).
6. Démarrer P1 (la 2e instance A1 est préparée à la fin de P1, avec un guide pas à pas).

## Hypothèses à vérifier

| Hypothèse | Avant |
| --- | --- |
| Instance A1 existante en plus d'`OracleWorker` (ex. `anime-notif-worker`) : à réutiliser ou supprimer, le quota gratuit n'en permet que deux de 1 OCPU / 6 Go | Fin de P1 |
| Santé de Procrastinate (dernière release, issues) | P1 |
| Quota réel du free tier Gemini | P8 |
| Rétention des événements UsageStats sur One UI ; survie de WorkManager à l'optimisation batterie | P7 |
| Mi Fitness écrit-il les séances dans Health Connect ? L'app Strava y écrit-elle ? | P9 |
| API Strava gratuite en usage personnel | P9 |
| Lecteur oEmbed TikTok utilisable | P10 |

## Problèmes connus

- Quota Oracle Always Free réduit en juin 2026 ; aucune marge pour un 3e serveur gratuit.

## Dette technique acceptée

- Aucune.

## Pour reprendre

Coller ce fichier en premier message d'une nouvelle conversation, puis la section de la phase en cours de `ROADMAP.md`.
