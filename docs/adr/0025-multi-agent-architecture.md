# ADR-0025 — Architecture multi-agents hiérarchique

- **Statut** : Validé (2026-11-08), décision D-H
- **Date** : 2026-11-08
- **Revue prévue** : Fin de la phase 3

## Contexte

Mission 3 : un Majordome unique dialogue avec l'utilisateur et coordonne six spécialistes autonomes (Sergent, Trésorier, Préparateur, Archiviste, Analyste, Veilleur). Contraintes : monolithe modulaire, pas un LLM par spécialiste, pas d'accès global aux données, aucune notification ni action non contrôlée.

## Décision

Le Majordome est le module `assistant` : routage d'intention en trois paliers (règles, similarité d'embeddings locaux, LLM léger si ambigu), synthèse et ton. Un spécialiste est un **module** qui déclare un `SpecialistProfile` dans son manifeste (ADR 0026). Correspondance : Sergent → `focus` (nouveau nom de `digital_activity`), Trésorier → `finance`, Préparateur → `fitness`, Archiviste → `knowledge`, Analyste → `chess`, Veilleur → `sentinel` (nouveau). Les modules `academic`, `projects`, `calendars`, `motivation`, `news` restent des modules de domaine sans profil d'agent. Les spécialistes communiquent par événements et par ports lus via le Core, jamais par appel direct. Seuls le Majordome et deux spécialistes (Archiviste, Sergent pour le découpage de tâches) utilisent un LLM ; les autres travaillent en SQL, règles, statistiques, ML local et algorithmes dédiés (Stockfish, FSRS).

## Alternatives rejetées

Un service ou un processus par agent (contraire à l'ADR 0001) ; spécialistes exposés comme simples outils choisis par le LLM (appel LLM supplémentaire, parallélisme non maîtrisé, contrats flous) ; framework d'agents externe (contraire à l'ADR 0006).

## Conséquences

Nouveau service `agents` dans le Core (ADR 0026). Le nom affiché du Majordome est configurable (`ASSISTANT_DISPLAY_NAME`). Un spécialiste se désactive comme un module. Extraction en service séparé possible plus tard sans changer le contrat.
