# ADR-0003 — PostgreSQL seul

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : > 10 utilisateurs ou > 1 M vecteurs

## Contexte

Volumes faibles ; chaque composant de stockage ajoute sauvegarde, supervision et migration.

## Décision

PostgreSQL 18 pour le relationnel, pgvector (HNSW, halfvec), la file de jobs (SKIP LOCKED), le cache applicatif (table + TTL) et le rate limiting par utilisateur.

## Alternatives rejetées

Redis, Qdrant ou Chroma en V1.

## Conséquences

Une seule base à sauvegarder et restaurer ; Redis réévalué au-delà du seuil.
