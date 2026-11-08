# ADR-0007 — Routing par tâche, classe de données et licence

- **Statut** : Accepté (amendé 2026-11-08)
- **Date** : 2026-11-08
- **Revue prévue** : À chaque changement de tarif majeur

## Contexte

Le free tier Gemini réutilise les données ; Claude Pro n'inclut pas de crédits API ; certaines sources interdisent l'usage IA (Strava).

## Décision

routing.yaml : personnel → Claude Haiku 5.5 (payant) ; public → Gemini Flash-Lite free tier ; sensitive ou no_ai → modèle local ou refus. Embeddings des données personnelles calculés localement (fastembed). pricing.yaml daté, budget et mode dégradé.

## Alternatives rejetées

Un seul fournisseur ; embeddings via API pour les données personnelles.

## Conséquences

Coût de quelques dollars par mois ; aucune donnée personnelle sur un free tier.
