# ADR-0005 — Frontend SPA + PWA : choix du framework

- **Statut** : Validé (2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : Avant la phase 3

## Contexte

Application privée, sans SEO, consommée surtout sur mobile, avec chat en streaming. Mission 0 avait recommandé SvelteKit ; la valeur de la compétence React pour l'employabilité est un critère du propriétaire. Mission 1 a ajouté un client Android natif sans UI métier (ADR 0013) : la PWA reste l'unique interface utilisateur.

## Décision

SPA React (Vite, TanStack Router et Query, shadcn/ui sur Radix, Tailwind) en PWA, servie statiquement par Caddy ; client API généré depuis l'OpenAPI. SvelteKit en mode SPA écarté.

## Alternatives rejetées

Next.js (SSR inutile pour une app privée) ; app native (coût double).

## Revue du 2026-11-12 (PR 34, avant la phase 3)

Pile confirmée. Précisions : routes déclarées en code (pas de génération de fichiers par le routeur) ; composants façon shadcn/ui copiés au besoin seulement ; réponses en flux lues par `fetch` (EventSource ne fait que des GET) ; service worker écrit à la main, sans Workbox (il ne cache que la coquille, jamais `/api/`) ; client typé par `openapi-typescript` et `openapi-fetch`, contrat vérifié en CI ; pnpm avec `minimumReleaseAge` (14 jours). Détails : `docs/frontend.md`.

## Conséquences

Aucun impact backend. Le design system (tokens, composants) est indépendant du framework.
