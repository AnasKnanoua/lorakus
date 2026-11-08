# ADR-0032 — Analyste : Stockfish comme moteur d'analyse

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Avant toute distribution du code

## Contexte

L'analyse des parties exige un calcul exact des coups, qu'un LLM réalise mal.

## Décision

Stockfish exécuté comme processus séparé via UCI, temps fixe par coup, priorité basse, de nuit, CPU plafonné ; lecture des parties et horloges avec `python-chess`. Gaffes détectées par chute d'évaluation ; exercices tirés des positions de l'utilisateur. Aucun LLM pour l'analyse.

## Alternatives rejetées

LLM pour l'analyse ; service d'analyse en ligne tiers (dépendance, conditions d'utilisation).

## Conséquences

`python-chess` et Stockfish sont sous GPL-3.0 : sans effet pour un usage personnel ou hébergé ; à revoir si le code de Lorakus est un jour distribué sous une licence incompatible.
