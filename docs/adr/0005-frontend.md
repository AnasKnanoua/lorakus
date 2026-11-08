# ADR-0005 — Frontend SPA + PWA : choix du framework

- **Statut** : Proposé
- **Date** : 2026-11-08
- **Revue prévue** : Avant la phase 3

## Contexte

Application privée, sans SEO, consommée surtout sur mobile, avec chat en streaming. Mission 0 avait recommandé SvelteKit ; la valeur de la compétence React pour l'employabilité est un critère du propriétaire. Mission 1 a ajouté un client Android natif sans UI métier (ADR 0013) : la PWA reste l'unique interface utilisateur.

## Décision

Proposé : SPA React (Vite, TanStack Router et Query, shadcn/ui sur Radix, Tailwind) en PWA, servie statiquement par Caddy ; client API généré depuis l'OpenAPI. Alternative retenue en second : SvelteKit en mode SPA.

## Alternatives rejetées

Next.js (SSR inutile pour une app privée) ; app native (coût double).

## Conséquences

Aucun impact backend. Le design system (tokens, composants) est indépendant du framework.
