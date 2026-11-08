# ADR-0008 — Multi-tenant dans les fondations

- **Statut** : Validé
- **Date** : 2026-11-08
- **Revue prévue** : Ouverture à d'autres utilisateurs

## Contexte

Le premier déploiement est personnel mais le Core ne doit pas supposer un seul utilisateur.

## Décision

user_id sur toute table métier, Row Level Security, session SQL avec app.current_user, rôle applicatif non superutilisateur, tests d'isolation à deux utilisateurs.

## Alternatives rejetées

Isolation applicative seule ; schéma par tenant.

## Conséquences

Coût faible dès le départ ; ajout ultérieur évité (la migration la plus risquée).
