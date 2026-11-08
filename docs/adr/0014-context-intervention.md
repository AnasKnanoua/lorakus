# ADR-0014 — Context Engine et InterventionPolicy dans le Core

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 11

## Contexte

Plusieurs modules veulent interrompre l'utilisateur ; trois systèmes de scoring concurrents mèneraient au spam.

## Décision

context calcule un PersonalContext à partir de l'Agenda et des ports fournis par les modules ; InterventionPolicy (dans signals) est le seul composant qui décide d'interrompre, avec niveaux, budget, cooldown et backoff.

## Alternatives rejetées

Notifications par module ; moteur de règles générique.

## Conséquences

Version minimale en phase 5, complétée en phase 7.
