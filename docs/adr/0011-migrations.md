# ADR-0011 — Migrations expand/contract

- **Statut** : Validé (exigence) / Accepté (méthode)
- **Date** : 2026-11-08
- **Revue prévue** : —

## Contexte

Les mises à jour ne doivent ni perdre de données ni empêcher un rollback.

## Décision

Alembic, une branche par module ; tout changement cassant en deux temps (expand puis contract une version plus tard) ; downgrade testé ; backup vérifié obligatoire avant toute migration irréversible ; migrations rejouées en CI.

## Alternatives rejetées

Migrations en une étape ; modifications manuelles en production.

## Conséquences

Rollback applicatif possible sans toucher au schéma.
