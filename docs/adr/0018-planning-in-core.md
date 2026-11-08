# ADR-0018 — Tâches et agenda dans le Core

- **Statut** : Proposé
- **Date** : 2026-11-08
- **Revue prévue** : Avant la phase 4

## Contexte

academic, projects et fitness créent des tâches et des créneaux ; le briefing et le planificateur ont besoin d'une vue unique.

## Décision

Proposé : service planning du Core (tâches génériques avec owner_module et ref, créneaux d'agenda, planificateur déterministe de journée et de semaine). Les modules métier restent minces et créent des tâches via le port.

## Alternatives rejetées

Module tasks dont les autres dépendent (dépendances entre modules) ; tâches par module (fusion coûteuse, conflits invisibles).

## Conséquences

Le Core gagne un domaine métier stable ; academic et projects deviennent plus simples.
