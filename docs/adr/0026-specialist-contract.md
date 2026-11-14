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

## Amendement du 2026-11-14 (PR 39) : orchestrateur livré, cache par durée de vie

- **Orchestrateur** (`core/agents/orchestrator.py`) : au plus 4 spécialistes en parallèle, délai de chacun borné par un plafond global de 3 s par question, aucune reprise ; disjoncteur par spécialiste (3 échecs, 15 minutes, puis un essai), le même que celui des fournisseurs d'IA ; dépend d'un contrat (`SpecialistDirectory`), pas du service concret.
- **Cache** : par durée de vie déclarée dans le profil (`cache_ttl_s`, 0 par défaut), par utilisateur, jamais pour un rapport en échec, en mémoire de l'API. **L'invalidation par événements est reportée** au premier spécialiste réel qui en a besoin (décision du propriétaire, 2026-11-14) : les événements sont traités par le worker, un autre processus que l'API.
- **Vers le modèle** : seuls les rapports d'un spécialiste dont la classe maximale n'est pas `sensitive` (en attendant le filtre par marqueurs, ADR 0027, P10), au statut `ok` ou `partial`, entrent dans le prompt, comme des données, dans un bloc qu'un rapport ne peut pas refermer ; jamais un fait `sensitive`. `core_agent_runs` enregistre `trace_id` (la réponse du chat) et les classes réellement transmises.
- **Trace « Pourquoi m'as-tu dit ça ? »** (scénario 7) : enregistrée avec chaque réponse (`asst_messages.trace`) : version du prompt, modèle, appels, coût, souvenirs fournis (par identifiant, jamais leur texte), outils et cartes, routage, spécialistes, classes de données transmises. Route `GET /api/v1/assistant/conversations/{id}/messages/{id}/trace`, bouton « Pourquoi ? » dans le chat.
