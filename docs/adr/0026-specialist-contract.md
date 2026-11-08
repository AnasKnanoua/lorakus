# ADR-0026 — Contrat des spécialistes, registre et orchestrateur

- **Statut** : Validé (2026-11-08), décision D-H
- **Date** : 2026-11-08
- **Revue prévue** : Fin de la phase 3

## Contexte

Le Majordome doit interroger plusieurs spécialistes sans charger leurs données brutes dans son contexte, avec des délais, des reprises et une traçabilité complète.

## Décision

Service `agents` du Core :

- **Registre** : lit les `SpecialistProfile` (nom, nom affiché, intentions, `data_scopes` limités aux tables du module, ports lus, classe maximale des rapports, usage LLM `none`/`formulation`/`analysis`, budget LLM mensuel, délai de réponse, préparations, actions possibles, limites rédigées). Un profil incomplet ou incohérent empêche le démarrage ; les intentions sont uniques entre spécialistes ; les dépendances (événements, ports) forment un graphe sans cycle de ports.
- **Contrat** : `SpecialistRequest` (identifiant, utilisateur, intention déclarée, paramètres typés, tranche de contexte, échéance, budget) et `SpecialistReport` (statut `ok`/`partial`/`no_data`/`timeout`/`error`, résumé de 1 à 3 phrases, faits typés avec classe, source et mention mesuré/estimé, confiance motivée, actions suggérées jamais exécutées, fraîcheur, coût). Rapport limité à 300 tokens.
- **Orchestrateur** : appels parallèles (au plus 4 par question), délai par spécialiste (3 s par défaut), aucune reprise en direct, disjoncteur de 15 min après pannes répétées, cache des rapports invalidé par les événements du spécialiste.
- **Traçabilité** : table append-only `core_agent_runs` (spécialistes appelés, statuts, durées, modèle, tokens, coût, classes de données transmises au LLM, décision, identifiant de trace).

## Alternatives rejetées

Contrat libre en texte (non testable) ; appels directs entre spécialistes (contraire à MODULE_SYSTEM).

## Conséquences

P2 : profil, registre, modèles et table ; P3 : orchestrateur et cache. Les champs `report_class` et `actions` existent dès P2, leur logique arrive avec le premier besoin réel (ADR 0027, 0028). Tests de contrat obligatoires pour chaque profil.
