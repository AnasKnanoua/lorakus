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
