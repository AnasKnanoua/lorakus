# ADR-0033 — Archiviste : graphe dans PostgreSQL et révisions FSRS

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 16

## Contexte

L'Archiviste relie ressources, notions, cours et projets, et organise des révisions espacées.

## Décision

Graphe de connaissances stocké dans PostgreSQL (table de nœuds et table d'arêtes typées, requêtes récursives), sans base de graphe dédiée (ADR 0003). Planification des révisions par l'algorithme ouvert FSRS. Résumés et questions de révision générés par LLM léger, par lot de nuit, citant toujours leur source, mis en cache. Mémoire personnelle, connaissances générales et documents importés toujours étiquetés.

## Alternatives rejetées

Base de graphe dédiée (composant supplémentaire) ; questions générées sans citation.

## Conséquences

Livré en phase 9.
