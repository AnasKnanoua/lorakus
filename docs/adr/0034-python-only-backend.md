# ADR-0034 — Python seul côté serveur, Rust seulement sur mesure

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : si un profilage montre un goulot d'étranglement CPU

## Contexte

Rust a été envisagé pour sa sécurité mémoire et ses performances. Dans Lorakus, le temps de réponse est dominé par les entrées-sorties (base de données, réseau, appels LLM de l'ordre de la seconde), pas par le calcul. Python est déjà sûr en mémoire ; les risques réels d'une application web (injections, authentification, permissions, fuites de secrets) ne dépendent pas du langage.

## Décision

Le backend reste en Python uniquement. Rust n'est introduit que si une mesure de profilage identifie une fonction précise limitée par le CPU ; elle est alors réécrite en module natif appelé depuis Python (PyO3 / maturin), sans modifier le reste du code. Lorakus bénéficie déjà d'outils écrits en Rust (uv, Ruff, pydantic-core).

## Alternatives rejetées

Backend entièrement en Rust (écosystème IA/ML principalement en Python, temps de développement multiplié pour un développeur seul) ; services mixtes Python et Rust (deux chaînes d'outils, deux CI, sans gain mesurable).

## Conséquences

Un seul langage serveur à maîtriser et à outiller. La porte reste ouverte, uniquement sur preuve mesurée.
