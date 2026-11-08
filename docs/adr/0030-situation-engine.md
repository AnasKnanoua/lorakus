# ADR-0030 — Moteur de situations

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 12

## Contexte

Plusieurs spécialistes émettent des signaux qui ne valent la peine d'interrompre l'utilisateur qu'en combinaison (mauvaise nuit et journée chargée ; session d'échecs longue et examen proche).

## Décision

Le service `signals` contient un moteur de **situations** : règles déclaratives combinant des signaux sur une fenêtre de temps et des conditions de contexte, produisant une situation avec ses preuves. Le moteur ne notifie jamais ; il transmet à l'`InterventionPolicy`, qui reste le seul décideur (ADR 0014, 0019). Les réactions de l'utilisateur ajustent les seuils par statistiques, puis par bandit contextuel en phase ML.

## Alternatives rejetées

Corrélation faite par chaque spécialiste (duplication, couplage) ; corrélation par LLM (coût, non déterministe).

## Conséquences

Livré en phase 5 avec les premières situations du Sergent v0 ; enrichi à chaque nouveau spécialiste.
