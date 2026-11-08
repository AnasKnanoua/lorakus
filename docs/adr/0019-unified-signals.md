# ADR-0019 — Signaux unifiés

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : —

## Contexte

Mission 0 prévoyait Notifier.propose appelé par les modules ; Mission 1 interdisait toute notification directe.

## Décision

Un seul point d'entrée Signals.emit(Signal) ; les rappels planifiés sont des signaux de type scheduled ; seule l'InterventionPolicy crée des notifications.

## Alternatives rejetées

Deux chemins (direct et via la politique).

## Conséquences

Budget, quiet hours et déduplication garantis pour toutes les sources.
