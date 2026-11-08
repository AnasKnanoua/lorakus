# ADR-0006 — Abstraction IA maison

- **Statut** : Accepté
- **Date** : 2026-11-08
- **Revue prévue** : Phase 15

## Contexte

Les frameworks d'orchestration changent vite et verrouillent l'architecture ; le besoin réel est restreint.

## Décision

Port AIProvider (chat, structured, embed, capabilities) et adaptateurs sur les SDK officiels ; ModelRouter maison.

## Alternatives rejetées

LangChain, LlamaIndex. Pydantic AI reste candidat comme implémentation d'adaptateur.

## Conséquences

Retry, fallback et routing écrits par nous ; contrôle total et tests simples avec FakeProvider.
