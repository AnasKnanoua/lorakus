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

Précision du 2026-11-11 (PR 23) : RLS activée **et forcée** sur chaque table, avec une politique par rôle (`TO lorakus_app` : lignes de l'utilisateur courant ; `TO lorakus_migrator` : tout, pour les migrations et les fonctions d'authentification). L'utilisateur courant est porté par `set_config('lorakus.user_id', …, true)`, de portée transaction, lu par `lorakus.current_user_id()`. Avant authentification, l'application n'utilise que des fonctions `SECURITY DEFINER` étroites (`auth_*`). Détail : `SECURITY.md` §4.1.
