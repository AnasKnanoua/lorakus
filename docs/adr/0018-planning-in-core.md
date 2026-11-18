# ADR-0018 — Tâches et agenda dans le Core

- **Statut** : Validé (2026-11-18, décision D-F)
- **Date** : 2026-11-08
- **Revue prévue** : Fin de la phase 5 (briefing et contexte branchés), ou avant toute ouverture commerciale

## Contexte

academic, projects et fitness créent des tâches et des créneaux ; le briefing et le planificateur ont besoin d'une vue unique.

## Décision

Proposé : service planning du Core (tâches génériques avec owner_module et ref, créneaux d'agenda, planificateur déterministe de journée et de semaine). Les modules métier restent minces et créent des tâches via le port.

## Alternatives rejetées

Module tasks dont les autres dépendent (dépendances entre modules) ; tâches par module (fusion coûteuse, conflits invisibles).

## Conséquences

Le Core gagne un domaine métier stable ; academic et projects deviennent plus simples.


## Amendement du 2026-11-18 : validation (D-F) et règles de mise en œuvre

Validé par le propriétaire avec le découpage de la phase 4 (`ROADMAP.md`). Raisons : les tâches et l'agenda sont lus par plusieurs modules (`academic`, `projects`, `calendars`, `focus`, puis `fitness`) et par des services du Core (`context` et heures calmes en P5, briefing) ; le Core n'importe jamais un module, et un module `tasks` dont les autres dépendraient est interdit par `MODULE_SYSTEM.md`. La mémoire suit déjà ce modèle : service du Core, outils du chat dans `assistant`.

Règles :

1. **Générique.** `planning` ne connaît ni devoir, ni coefficient, ni projet : une tâche porte `owner_module` et `owner_ref` (nuls pour une tâche personnelle), et le module propriétaire garde le sens métier dans ses tables. Une tâche d'un module ne se modifie que par ce module (port `Tasks`) ou par l'utilisateur ; quand l'utilisateur la termine, l'événement `planning.task_completed` prévient le module.
2. **Le temps.** Tout instant est stocké en UTC (`timestamptz`). Le fuseau de l'utilisateur est un réglage de son compte (nom IANA, par exemple `Europe/Istanbul`), seul utilisé pour dire « aujourd'hui », placer un créneau ou donner l'heure au modèle ; jamais le fuseau du serveur. L'interface envoie le fuseau du navigateur ; s'il diffère du réglage, elle propose de le changer, sans changement silencieux (un job de nuit n'a pas de navigateur : le réglage doit rester la seule vérité). Une échéance « pour vendredi » est une date locale, rendue en fin de journée dans le fuseau de l'utilisateur.
3. **L'agenda reste simple.** Il ne contient que des créneaux concrets, sans règle de répétition : `calendars` déplie les récurrences des fichiers ICS (RRULE, EXDATE, RECURRENCE-ID) sur une fenêtre glissante et remplace les créneaux de sa source de façon idempotente. Toute la complexité des récurrences reste dans ce module.
4. **Le planificateur est déterministe et propose.** Le plan du jour est calculé à la demande à partir de l'agenda, des tâches et des préférences confirmées ; il n'écrit jamais dans l'agenda et n'appelle aucun LLM. Aucune tâche planifiée par utilisateur (`MODULE_SYSTEM.md` §11).

Mise en œuvre (PR 44) : tables `core_account_settings`, `core_tasks` et `core_agenda_entries` (migration 0013, RLS forcée, contraintes écrites pour ne jamais valoir NULL) ; fonctions dans la transaction de l'appelant (une carte de confirmation crée la tâche dans la même transaction que sa décision) ; ports `ModuleTasks` et `ModuleAgenda`. L'événement `planning.task_completed` arrive avec son premier consommateur, `academic` (PR 46) : aucun mécanisme sans consommateur.
