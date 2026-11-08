# ADR-0020 — Intégrations externes du MVP

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 8

## Contexte

Le MVP doit s'intégrer à des outils externes sans dépendre d'OAuth fragile.

## Décision

Abonnements ICS en lecture (calendrier Google via adresse secrète, emploi du temps de l'école) ; bot Telegram (notifications, alertes, capture) ; Web Push ; API Claude.

## Alternatives rejetées

OAuth Google Calendar (jetons limités tant que l'app n'est pas vérifiée) ; ntfy (service supplémentaire).

## Conséquences

Écriture dans le calendrier reportée.
