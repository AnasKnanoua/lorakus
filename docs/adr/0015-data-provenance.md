# ADR-0015 — Provenance et contraintes de licence des données

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : À chaque nouveau connecteur

## Contexte

Le contrat API Strava interdit l'usage de ses données dans des modèles d'IA ; les données de santé relèvent de l'article 9 du RGPD.

## Décision

Chaque enregistrement porte source et license_constraints ; les données de santé sont sensitive ; le ModelRouter et le pipeline ML refusent structurellement no_ai et sensitive vers l'extérieur.

## Alternatives rejetées

Contrôle au cas par cas dans les modules.

## Conséquences

Colonne présente dès la phase 2, logique active à partir de la phase 9.
