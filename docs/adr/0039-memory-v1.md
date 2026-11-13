# ADR-0039 — Mémoire v1 : propositions vérifiées, confirmation obligatoire

- **Statut** : Validé (2026-11-12, plan accepté par le propriétaire)
- **Date** : 2026-11-12
- **Revue prévue** : avec la PR 37 (recherche par embeddings) et avant toute ouverture commerciale

## Contexte

L'assistant doit retenir ce que l'utilisateur lui apprend sur lui (préférences, projets, habitudes) sans jamais transformer une conversation en mémoire permanente à son insu (spécification, §4). Un modèle peut inventer, mal comprendre, ou être manipulé par un texte collé dans la conversation.

## Décision

**Service `memory` du Core** (tables `core_memory_facts`, `core_memory_rejections`, `core_memory_settings`, migration 0009, RLS forcée).

- Un fait : une ligne de 300 caractères au plus, une catégorie dans une liste fermée (`identity`, `preference`, `project`, `habit`, `studies`, `other`), un statut, une classe de données et sa provenance (ADR 0015 : `source_kind`, `source_ref`, `evidence`, `license_constraints`).
- Statuts : `proposed` (en attente de l'utilisateur), `verified` (confirmé par lui, seul utilisé), `inferred` (réservé, sans producteur en v1). Une contrainte de la base lie `verified` à une date de confirmation.
- **Seul l'utilisateur confirme.** Une conversation ne crée que des propositions ; un fait saisi par l'utilisateur lui-même est confirmé d'emblée.

**Propositions après une conversation**, quelques minutes après le dernier message (`LORAKUS_MEMORY_PROPOSAL_DELAY_SECONDS`, 180 par défaut ; un nouveau message repousse l'analyse) :

- seuls les **messages de l'utilisateur** sont analysés, jamais les réponses de l'assistant (ni ses erreurs ni un texte qu'il aurait reproduit ne deviennent des souvenirs) ;
- sortie JSON validée par un schéma (`complete_structured`, tâche `memory.extract` du `ModelRouter`, coût dans le plafond mensuel) ;
- contrôles **déterministes** après le modèle : chaque fait cite un extrait de l'un des messages, retrouvé mot pour mot (espaces et casse ignorés), sinon il est écarté ; un fait déjà connu ou déjà refusé est écarté ; au plus 5 propositions par analyse, 20 en attente, 200 faits confirmés ;
- le prompt demande d'ignorer les données sensibles (santé, religion, opinions, finances, identifiants) et de n'obéir à aucune instruction des messages ; ce n'est qu'une consigne, les garanties sont les contrôles ci-dessus et la confirmation ;
- point de reprise par conversation (`asst_conversations.memory_scanned_until`) : un message non analysé (moteur IA indisponible, budget atteint, propositions au maximum) le sera à l'analyse suivante ; quand l'utilisateur a désactivé les propositions, ses messages ne sont jamais analysés, même après réactivation.

L'analyse tourne dans le processus de l'API (`DebouncedTasks`), car seule l'API reçoit la clé du fournisseur ; elle est perdue à un redémarrage et refaite au message suivant.

**Utilisation** : les faits confirmés de classe `personal` entrent dans le prompt système de l'assistant, dans un bloc `<faits>` présenté comme des données et non des instructions, une ligne par fait, au plus 60 faits et 1 500 tokens estimés, les plus récents d'abord. Un fait `sensitive` n'est jamais remis au modèle (fournisseur externe).

**Contrôle par l'utilisateur** (page `/memoire`) : confirmer, corriger puis confirmer, refuser (le texte est effacé, seule une empreinte SHA-256 empêche de le reproposer), modifier, supprimer, ajouter, désactiver les propositions, tout oublier (ré-authentification de moins de 10 minutes). Le journal d'audit enregistre chaque décision avec l'identifiant du fait, jamais son contenu.

## Alternatives rejetées

- Mémorisation automatique sans confirmation : erreurs et manipulations deviennent des « vérités » durables.
- Analyse de toute la conversation, réponses comprises : le modèle se citerait lui-même.
- Tâche Procrastinate dans le worker : demanderait de donner la clé du fournisseur au worker.
- Embeddings et recherche dès la v1 : inutiles tant que tous les faits tiennent dans le prompt (PR 37).

## Conséquences

- Le prénom, une préférence ou un projet dits en conversation sont utilisés dès leur confirmation.
- Une analyse coûte environ un dixième de centime avec Haiku 5.5 ; elle est bornée par le rythme IA par utilisateur (ADR 0038).
- L'empreinte d'un texte refusé, non salée, pourrait être retrouvée pour un texte très court et devinable ; acceptable pour une information que l'utilisateur a lui-même écartée, à revoir si un client l'exige.
