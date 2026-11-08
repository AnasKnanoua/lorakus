# ADR-0021 — Socle de versions

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Tous les 12 mois

## Contexte

Mission 0 citait PostgreSQL 16 ; il faut un socle explicite et daté.

## Décision

Python 3.13 (gérée par uv), PostgreSQL 18 (image pgvector/pgvector:pg18), Node.js LTS, Kotlin et JDK 21 pour Sensors. Toutes les images et versions sont épinglées.

## Alternatives rejetées

Python 3.14 (compatibilité ARM64 de certaines roues à vérifier) ; PostgreSQL 16 ou 17.

## Conséquences

Le volume PostgreSQL 18 se monte sur /var/lib/postgresql (changement de répertoire de l'image).
