# ADR-0012 — Contenu externe non fiable, outils à permissions

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Après chaque campagne red team

## Contexte

Le prompt injection ne se corrige pas, il se contient.

## Décision

Profil ingest (contenu externe, aucun outil, sortie structurée) séparé du profil assistant ; outils déclarés avec permission et niveau de risque ; confirmation pour write et sensitive ; budgets d'itérations ; corpus d'injections en CI.

## Alternatives rejetées

Filtrage par expressions régulières seul.

## Conséquences

Quelques confirmations supplémentaires pour l'utilisateur.

## Amendement du 2026-11-21 (PR 51) : `inert()` dans le Core

La neutralisation des textes venus de l'utilisateur ou de l'extérieur avant qu'ils n'atteignent le modèle (`inert()`, avec ses délimiteurs `SAFE_LT` et `SAFE_GT`) vit désormais dans `lorakus/core/tools/inert.py`. Un module qui expose un outil de lecture au chat (le module `projects` le premier) l'utilise sans importer le module `assistant`, ce que l'architecture interdit (import-linter). `lorakus_modules/assistant/prompts.py` la réexporte : rien ne change pour ses appelants.
