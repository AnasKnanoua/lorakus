# ADR-0004 — File de jobs Procrastinate derrière le port JobQueue

- **Statut** : Accepté (amendé 2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : Si la maintenance de Procrastinate faiblit

## Contexte

Jobs différés et périodiques persistants, sans broker supplémentaire. Procrastinate publie des versions (3.5.x) mais cherche des mainteneurs.

## Décision

Port JobQueue dans le Core (enqueue, periodic, retry, lock) ; implémentation Procrastinate. Les modules n'importent jamais Procrastinate.

## Alternatives rejetées

APScheduler seul (non persistant) ; Celery + Redis (infrastructure en plus).

## Conséquences

Remplacement possible par une table SKIP LOCKED maison (~200 lignes) sans toucher aux modules.
