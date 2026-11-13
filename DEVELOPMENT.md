# Développement

## 1. Prérequis (poste de développement Ubuntu)

| Outil | Rôle |
| --- | --- |
| Git, GitHub CLI (`gh`) | Dépôt, pull requests |
| Docker Engine + plugin Compose | Environnement local identique à la prod |
| `uv` | Python 3.13 et dépendances du backend |
| Node.js LTS + `pnpm` | Frontend et extension navigateur |
| `pre-commit`, Gitleaks | Contrôles locaux avant commit |
| `age` | Chiffrement des sauvegardes |
| JDK 21, Android Studio, `adb` | À partir de la phase 7 (LORAKUS Sensors) |

## 2. Arborescence

```
lorakus/
├── backend/
│   ├── lorakus/              # Core : core/, ai/, connectors/, db/, api/, worker/, observability/
│   ├── lorakus_modules/      # un package par module + _template
│   ├── alembic/             # env.py multi-branches
│   ├── tests/               # unit/, integration/, contract/, isolation/
│   └── evals/               # Promptfoo : jeux de tests LLM et corpus d'injections
├── frontend/                # SPA + PWA (framework : ADR 0005)
├── extension/               # extension navigateur MV3 (phase 7)
├── android/                 # LORAKUS Sensors (phase 7)
├── infra/                   # compose, caddy, observability, postgres, backup, redteam
├── scripts/                 # new_module.py, anonymize.sql, seed_dev.py
└── docs/                    # adr/, modules/, runbooks/, incidents/, design/, db/
```

## 3. Commandes

| Commande | Effet |
| --- | --- |
| `make bootstrap` | Installe les dépendances (uv, pnpm) et les hooks pre-commit |
| `make dev` | Lance la pile locale |
| `make test` | Tests unitaires et d'intégration (Postgres via testcontainers) |
| `make e2e` | Tests Playwright sur une pile éphémère |
| `make lint` | Ruff, pyright strict, ESLint, import-linter |
| `make security` | Bandit, Semgrep, pip-audit, Gitleaks |
| `make migration BRANCH=core MSG="..."` | Nouvelle révision Alembic sur la branche du module (`core`, `academic`…) |
| `make migrate` | Applique les migrations en local |
| `make evals` | Evals Promptfoo sur `FakeProvider` |
| `make new-module NAME=...` | Crée un module depuis le gabarit |
| `make front-dev` | Lance l'interface sur http://localhost:5173 ; `/api` est relayé vers `localhost:8001` (tunnel SSH vers la production, ou pile locale) |
| `make front-check` | Frontend : ESLint, TypeScript strict, tests (parcours, accessibilité) et construction |
| `make openapi` | Après un changement d'API : régénère `frontend/openapi.json` et le client TypeScript (la CI refuse un contrat périmé) |

## 4. Circuit d'une modification

Une modification fait toujours le même trajet : **Dell → PR → `main` → serveur**. Fusionner ne touche pas au serveur ; seul le déploiement le fait, et il attend ton approbation.

| Étape | Commande | Ce qui se passe |
| --- | --- | --- |
| 1. Proposer | `make pr PATCH=~/Téléchargements/x.patch BRANCH=feat/x TITLE="feat(core): ..."` | Branche à jour de `main`, patch appliqué, commit, PR ouverte, vérifications suivies jusqu'au bout |
| 2. Fusionner | `make merge` (quand tout est vert) | Squash dans `main`, retour sur `main` à jour |
| 3. Déployer | `make deploy` (si la PR change ce qui tourne sur le serveur) | Staging jetable, puis la page d'approbation s'ouvre : « Review deployments » → « Approve » |
| Annuler | `make rollback` | Version précédente remise en service |
| Vérifier | `make prod-status` | Version en service et précédente |
| Publier une version (fin de phase) | `make release-pr VERSION=0.2.0`, puis `make merge` sur la PR de version, puis `make release` | `release-please` écrit le CHANGELOG à partir des titres de PR, met à jour le numéro, puis crée le tag et la release |

Le message de livraison de chaque PR dit si l'étape 3 est nécessaire.

## 5. Git et revue

- Trunk-based : branches courtes `feat/…`, `fix/…`, `chore/…`, `docs/…` ; protection de `main` (CI verte obligatoire, pas de push direct).
- Pull request obligatoire, même seul : la CI est le relecteur ; squash merge.
- Format Conventional Commits : `type(scope): description` — types `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `build`, `perf` ; scope = module ou `core` (ex. `feat(academic): ajoute la détection de retard`) ; `!` ou `BREAKING CHANGE:` pour une rupture de compatibilité.
- Fusion par squash : **le titre de la PR devient le commit sur `main`** et doit respecter le format (vérifié en CI à partir de la phase 1) ; les commits intermédiaires de la branche sont libres.
- `release-please` génère le CHANGELOG, le numéro de version (`backend/lorakus/__init__.py`) et les tags à partir de l'historique de `main`. Il est lancé depuis le poste (`make release-pr`, `make release`) avec le compte `gh` : aucun jeton d'écriture n'est confié à la CI, et la PR de version déclenche les vérifications normalement.
- Template de PR : tests, migration, documentation du module, `PROJECT_STATE.md`, impact sécurité (nouvel outil IA ? nouvelle donnée sensible ? nouvelle dépendance justifiée ?).

## 6. Standards de code

- Python : Ruff (lint + format), pyright en mode strict sur `lorakus/` et `lorakus_modules/`, docstrings sur les ports et cas d'usage.
- Pas de logique métier dans les routes ; pas d'accès base hors `infrastructure`.
- Frontend : TypeScript strict, ESLint, client API généré depuis l'OpenAPI, aucun appel `fetch` écrit à la main vers l'API.
- Dépendances : toute nouvelle dépendance est justifiée dans la PR ; une dépendance sans release depuis 12 mois déclenche une revue.

## 7. Tests

| Niveau | Outil | Cible |
| --- | --- | --- |
| Unitaires | pytest | Domaine et cas d'usage ; couverture ≥ 80 % sur `domain` et `application` |
| Intégration | pytest + testcontainers (PostgreSQL 18) | Repositories, migrations, RLS, jobs |
| Contrat | pytest | Manifestes, ports, événements (`schema_version`) |
| Isolation | pytest | Chaque table et chaque route testées avec deux utilisateurs |
| Architecture | import-linter (`make lint`) | Le Core n'importe jamais un module ; modules indépendants entre eux ; couches `api → core → db, observability → settings` |
| LLM | Promptfoo | Comportement sur `FakeProvider` en CI ; vrais fournisseurs chaque semaine |
| E2E | Playwright | Scénarios d'acceptation du MVP |
| Frontend | Vitest, axe-core | Composants et accessibilité |
| Évaluation | pytest (`backend/tests/evals/`) | Qualité de la recherche dans la mémoire (recall@5, MRR) sur un jeu étiqueté fictif. Faux modèle dans `make check` ; vrai modèle dans la CI (étape « Évaluation de la recherche »). En local : `infra/models/fetch-embedding-model.sh /tmp/model && LORAKUS_EMBEDDING_MODEL_DIR=/tmp/model uv --directory backend run pytest -s tests/evals` |

## 8. Migrations

1. Modifier les modèles SQLAlchemy du module.
2. `make migration MODULE=<module> MSG="ajoute colonne x"` puis relire le fichier généré.
3. Changement cassant : expand d'abord (colonne nullable, double écriture), contract à la version suivante.
4. Écrire le `downgrade` ; marquer `irreversible = True` si impossible.
5. La CI rejoue `upgrade heads`, `downgrade -1`, `upgrade heads`, puis `alembic check`.

## 9. Définition de « terminé »

Une fonctionnalité est terminée quand : le code est fusionné, les tests passent en CI, la migration est rejouable, la documentation du module est à jour, l'observabilité couvre le nouveau chemin (logs, métrique, span), et `PROJECT_STATE.md` reflète le nouvel état.

## 10. Reprendre après une pause

Lire `PROJECT_STATE.md`, puis `DECISIONS.md` (décisions récentes), puis la phase en cours dans `ROADMAP.md`. Dans une conversation avec Claude, coller `PROJECT_STATE.md` en premier message.
