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

## Amendement du 2026-11-22 (P5, ADR 0042) : mise en œuvre

`Signals.emit` est `lorakus.core.signals.service.emit(session, user_id, module, SignalDraft)`, dans la transaction de l'appelant. Une cause est unique par utilisateur (`dedup_key`), y compris après son retrait ou son expiration ; `withdraw` retire une cause qui n'en est plus une. Les textes sont écrits par le code du module, jamais par un modèle. Seul le job `signals.dispatch` crée une carte (niveau 1) ou une notification (niveau 2).
