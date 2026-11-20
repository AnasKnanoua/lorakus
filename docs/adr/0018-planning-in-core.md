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

## Amendement du 2026-11-20 (PR 46) : l'événement `planning.task_completed`

Arrivé avec son premier consommateur, le module `academic`.

1. **Quand.** Publié par `complete_task` (l'utilisateur termine une tâche, aujourd'hui par la carte du chat) **seulement si la tâche appartient à un module**, dans la transaction qui la termine (outbox) : pas d'événement sans tâche terminée, pas de tâche terminée sans événement. Une tâche personnelle n'a personne à prévenir. Un module qui termine lui-même sa tâche (`ModuleTasks.complete`) n'en reçoit pas : il le sait déjà, et un événement en retour ferait une boucle.
2. **Charge utile.** `task_id`, `owner_module`, `owner_ref` : des identifiants seulement.
3. **Chaque consommateur filtre et revérifie.** Tous les modules abonnés reçoivent l'événement : chacun ignore ceux dont `owner_module` n'est pas le sien, puis relit la tâche par son port avant d'agir (elle doit exister, lui appartenir et être terminée). L'événement est un signal, pas une preuve : rejoué (livraison au moins une fois), forgé par un autre utilisateur ou arrivé en retard, il ne change rien à tort.
4. **Module désactivé.** Le handler agit quand même : désactiver un module ne supprime pas ses données, qui doivent rester justes au retour.

Déplacé à cette occasion : l'écriture des dates en français (`french_date`, `relative_day`, `duration`) passe du module `assistant` au Core (`lorakus/core/account/dates.py`), pour que la carte d'un autre module donne la date exactement comme celles des tâches sans importer un module (interdit).

Tests : `tests/integration/test_academic.py` (événement de bout en bout avec le relais du worker, tâche personnelle sans événement, événements faux, rejoués, d'un autre module ou d'un autre utilisateur).

## Amendement du 2026-11-20 (PR 47) : le planificateur de journée

Le planificateur (`lorakus/core/planning/planner.py`) est un ensemble de fonctions pures : elles reçoivent l'instant présent, le fuseau du compte, les créneaux du jour et les tâches ouvertes, et rendent un plan. Aucune base, aucun réseau, aucun LLM. Le plan est recalculé à chaque lecture (`today.py`, route `GET /api/v1/planning/today`) et n'est écrit nulle part : la route ouvre sa transaction en lecture seule, si bien que PostgreSQL lui-même refuserait une écriture.

Règles, dans l'ordre :

1. **Fenêtre de travail** : de 8 h à 22 h, heure du compte, à partir de maintenant (arrondi au quart d'heure suivant). Après 22 h, plus de plan pour ce jour.
2. **Créneaux libres** : la fenêtre moins les créneaux horaires de l'agenda, fusionnés s'ils se chevauchent ou se touchent. Une journée entière n'occupe pas d'heures. Un trou de moins de 15 minutes n'est pas un créneau.
3. **Tâches retenues** : les tâches ouvertes sans sous-tâche ouverte. Une sous-tâche sans échéance prend celle de sa tâche.
4. **Ordre** : échéance la plus proche d'abord (les retards sont donc en tête), tâches sans échéance à la fin ; puis priorité haute d'abord ; puis la plus courte ; puis la plus ancienne ; enfin l'identifiant, pour qu'un même état donne toujours le même plan.
5. **Durée** : la durée estimée, sinon 30 minutes, signalées « durée supposée ».
6. **Placement** : chaque tâche, dans l'ordre, prend le premier temps libre. Un bloc dure 2 h au plus et 30 minutes au moins, sauf s'il termine la tâche ; 15 minutes de pause suivent chaque bloc ; une tâche trop longue pour un créneau continue dans le suivant.
7. **Plafond** : 6 h de travail proposées par jour. Ce qui ne tient pas est rendu avec le temps restant (« Pas de place aujourd'hui »), jamais caché.

Ces nombres sont des constantes : la PR 50 en fera des préférences confirmées (plage de travail, heure limite, jours sans travail). Limites connues, voulues pour l'instant : le plan ne regarde que le jour même (pas de répartition sur la semaine) ; il ne tient pas compte des trajets ni de l'énergie ; une tâche lointaine est proposée dès qu'il reste de la place.

Tests : `tests/unit/test_planner.py` (chaque règle, puis 60 journées tirées au hasard à graine fixe : jamais deux blocs en même temps, jamais pendant un créneau de l'agenda, toujours la pause, jamais plus de 6 h, aucune minute perdue ni inventée), `tests/integration/test_today.py` (fuseau du compte, RLS, lecture seule, scénario 2).
