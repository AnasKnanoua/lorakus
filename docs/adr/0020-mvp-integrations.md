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


Amendement du 2026-11-09 : les alertes d'exploitation passent par Discord (ADR 0035) ; Telegram est réservé aux notifications du produit.

## Amendement du 2026-11-22 (P5, ADR 0042)

Web Push devient le canal principal des notifications du produit (contenu chiffré de bout en bout) ; Telegram sert à la capture d'idées et de second canal, sans contenu personnel.
