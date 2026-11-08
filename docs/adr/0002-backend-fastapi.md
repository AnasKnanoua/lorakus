# ADR-0002 — Backend FastAPI + SQLAlchemy 2 + Alembic

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 6

## Contexte

Besoin d'async (SSE, appels IA), d'un typage fort et de l'écosystème Python IA/ML.

## Décision

Python, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, structlog, httpx.

## Alternatives rejetées

Django (ORM à modèles actifs contraire à la séparation domaine/infrastructure) ; NestJS, Go (perte de l'écosystème ML).

## Conséquences

Assemblage de briques plutôt que framework tout-en-un ; architecture hexagonale naturelle.
