# ADR-0014 — Context Engine et InterventionPolicy dans le Core

- **Statut** : Accepté — complété par l'ADR 0030 (moteur de situations)
- **Date** : 2026-11-08
- **Revue prévue** : Phase 11

## Contexte

Plusieurs modules veulent interrompre l'utilisateur ; trois systèmes de scoring concurrents mèneraient au spam.

## Décision

context calcule un PersonalContext à partir de l'Agenda et des ports fournis par les modules ; InterventionPolicy (dans signals) est le seul composant qui décide d'interrompre, avec niveaux, budget, cooldown et backoff.

## Alternatives rejetées

Notifications par module ; moteur de règles générique.

## Conséquences

Version minimale en phase 5, complétée en phase 7.

## Amendement du 2026-11-22 (P5, ADR 0042) : version minimale

L'`InterventionPolicy` est livrée dans le Core (`lorakus/core/signals/policy.py`), seule à décider d'interrompre, avec niveaux, budget, heures calmes et dédoublonnage. Le Context Engine (`PersonalContext`) n'est **pas** construit en P5 : son seul consommateur serait la politique, qui lit directement le cadre du jour et le planning. Il viendra avec un second consommateur (situations, P10). Heures calmes : la plage de travail donnée pour le jour en cours, rien n'est supposé.
