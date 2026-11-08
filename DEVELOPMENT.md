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
| `make migration MODULE=academic MSG="..."` | Nouvelle révision Alembic sur la branche du module |
| `make migrate` | Applique les migrations en local |
| `make evals` | Evals Promptfoo sur `FakeProvider` |
| `make new-module NAME=...` | Crée un module depuis le gabarit |

## 4. Git et revue

- Trunk-based : branches courtes `feat/…`, `fix/…`, `chore/…`, `docs/…` ; protection de `main` (CI verte obligatoire, pas de push direct).
- Pull request obligatoire, même seul : la CI est le relecteur ; squash merge.
- Messages au format Conventional Commits (`feat(academic): …`) ; `release-please` génère le CHANGELOG et les tags.
- Template de PR : tests, migration, documentation du module, `PROJECT_STATE.md`, impact sécurité (nouvel outil IA ? nouvelle donnée sensible ? nouvelle dépendance justifiée ?).

## 5. Standards de code

- Python : Ruff (lint + format), pyright en mode strict sur `lorakus/` et `lorakus_modules/`, docstrings sur les ports et cas d'usage.
- Pas de logique métier dans les routes ; pas d'accès base hors `infrastructure`.
- Frontend : TypeScript strict, ESLint, client API généré depuis l'OpenAPI, aucun appel `fetch` écrit à la main vers l'API.
- Dépendances : toute nouvelle dépendance est justifiée dans la PR ; une dépendance sans release depuis 12 mois déclenche une revue.

## 6. Tests

| Niveau | Outil | Cible |
| --- | --- | --- |
| Unitaires | pytest | Domaine et cas d'usage ; couverture ≥ 80 % sur `domain` et `application` |
| Intégration | pytest + testcontainers (PostgreSQL 18) | Repositories, migrations, RLS, jobs |
| Contrat | pytest | Manifestes, ports, événements (`schema_version`) |
| Isolation | pytest | Chaque table et chaque route testées avec deux utilisateurs |
| Architecture | import-linter | Frontières entre modules et Core |
| LLM | Promptfoo | Comportement sur `FakeProvider` en CI ; vrais fournisseurs chaque semaine |
| E2E | Playwright | Scénarios d'acceptation du MVP |
| Frontend | Vitest, axe-core | Composants et accessibilité |

## 7. Migrations

1. Modifier les modèles SQLAlchemy du module.
2. `make migration MODULE=<module> MSG="ajoute colonne x"` puis relire le fichier généré.
3. Changement cassant : expand d'abord (colonne nullable, double écriture), contract à la version suivante.
4. Écrire le `downgrade` ; marquer `irreversible = True` si impossible.
5. La CI rejoue `upgrade heads`, `downgrade -1`, `upgrade heads`, puis `alembic check`.

## 8. Définition de « terminé »

Une fonctionnalité est terminée quand : le code est fusionné, les tests passent en CI, la migration est rejouable, la documentation du module est à jour, l'observabilité couvre le nouveau chemin (logs, métrique, span), et `PROJECT_STATE.md` reflète le nouvel état.

## 9. Reprendre après une pause

Lire `PROJECT_STATE.md`, puis `DECISIONS.md` (décisions récentes), puis la phase en cours dans `ROADMAP.md`. Dans une conversation avec Claude, coller `PROJECT_STATE.md` en premier message.
