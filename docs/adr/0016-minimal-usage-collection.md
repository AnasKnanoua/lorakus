# ADR-0016 — Collecte d'usage numérique minimale

- **Statut** : Accepté — amendé par l'ADR 0029 (blocage uniquement par pactes volontaires)
- **Date** : 2026-11-08
- **Revue prévue** : Phase 11

## Contexte

Mesurer l'usage des réseaux sociaux sans collecte clandestine ni mécanisme fragile.

## Décision

UsageStatsManager et extension navigateur uniquement ; sessionisation sur l'appareil ; catégorie de page sans URL complète ; pas d'AccessibilityService ; NotificationListener optionnel et désactivé par défaut ; aucun blocage par LORAKUS (délégué au Bien-être numérique du système).

## Alternatives rejetées

Service d'accessibilité ; VPN local d'inspection ; scraping des apps.

## Conséquences

Le contenu regardé reste inconnu : les classifications sont des probabilités affichées comme telles.
