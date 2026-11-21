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

## Amendement du 2026-11-20 (PR 48) : préférences de planification

Retour d'usage le jour de la PR 47 : le plan ignore les repas et les horaires réels de la personne. Les préférences, prévues en fin de phase (PR 50), passent avant le Sergent, qui résume un plan : autant qu'il soit juste.

1. **Catalogue fermé** (`lorakus/core/planning/preferences.py`, table `core_planning_preferences`, migration 0014, RLS forcée) : `work_start` et `work_end` (bornes de la journée de travail, 8 h et 22 h par défaut), `lunch` et `dinner` (plages de repas, aucune par défaut), `rest_days` (jours sans travail, aucun), `daily_cap` (travail proposé par jour, 6 h). Chaque valeur est typée et bornée : un repas dure de 15 minutes à 3 heures, la journée de travail au moins une heure, le plafond de 30 minutes à 12 heures, et jamais sept jours sans travail. Aucun texte libre.
2. **Confirmation par carte, pas par la mémoire.** La roadmap prévoyait des préférences « proposées par la mémoire » (analyse quelques minutes après la conversation, confirmation dans `/memoire`). Décision : une **carte de confirmation dans le chat** (ADR 0040), outils `assistant.set_preference` et `assistant.clear_preference`. Raisons : la confirmation est immédiate, au moment où la personne le dit ; la valeur est validée par le code avant la carte ; la carte montre la valeur proposée et la valeur actuelle ; aucun nouveau schéma d'extraction à évaluer. La règle de l'ADR 0039 est respectée : rien n'est retenu sans confirmation. L'extraction par la mémoire pourra s'y ajouter plus tard comme second producteur, sans changer le stockage ni le planificateur.
3. **Lecture tolérante.** Une ligne dont la valeur ne se lit plus est ignorée ; si l'ensemble est incohérent, tous les défauts s'appliquent : le planificateur ne tombe jamais à cause d'une préférence.
4. **Effet sur le plan** : fenêtre de travail tirée des bornes ; repas ajoutés au temps occupé et montrés dans le déroulé ; aucun plan un jour sans travail (les échéances restent visibles) ; plafond du jour.
5. **Page « Ma journée »** : section « Mes préférences » (les six, confirmées ou par défaut), où l'on peut en retirer une ; `GET /api/v1/planning/preferences`, `DELETE /api/v1/planning/preferences/{key}`. Les régler se fait en le disant à Lorakus.

Non couvert : les activités récurrentes (sport, trajets) sont des créneaux d'agenda, pas des préférences ; les préférences par jour de la semaine (déjeuner plus tard le vendredi) attendront un besoin réel.

Tests : `tests/unit/test_preference_catalogue.py`, `tests/unit/test_planner.py` (préférences), `tests/integration/test_planning_preferences.py` (service sous RLS, lignes illisibles, cartes, routes, scénario 6), corpus d'injections (position 7), banc (3 cas).

## Amendement du 2026-11-21 (PR 49) : le cadre du jour remplace les préférences fixes

Retour d'usage de la PR 48, le jour même : des horaires fixes ne décrivent pas la vie du propriétaire. Il mange à 18 h un jour, à 22 h le lendemain, une fois ou pas du tout ; il fait des nuits blanches ; il ne se lève pas à 8 h. Un planificateur qui suppose des heures place du travail quand il dort et rend le plan faux, donc inutile. L'amendement de la PR 48 est remplacé :

1. **Aucune heure supposée.** Le planificateur ne lit plus de bornes par défaut : sans cadre pour le jour, aucun créneau n'est proposé. La page dit ce qui est à faire et pour quand, et propose d'en parler à Lorakus.
2. **Cadre du jour** (`lorakus/core/planning/days.py`, table `core_planning_days`, migration 0015, RLS forcée) : pour UN jour local, soit « pas de travail », soit une plage de travail et ses pauses (repas, pause, sport, autre). La plage commence le jour dit dans le fuseau du compte ; une fin plus tôt que le début tombe le lendemain (« de 22 h à 4 h ») ; de 30 minutes à 20 heures. Une pause tient dans la plage, de 10 minutes à 4 heures, 6 au plus. Les heures sont converties en instants UTC une fois pour toutes. Il se donne en conversation, confirmé par une carte (`assistant.set_day`) ; il s'efface depuis la page (`DELETE /api/v1/planning/days/{day}`).
3. **Journée en cours.** Tant que la plage de la veille n'est pas finie, la journée en cours est celle de la veille : à 2 h du matin pendant une nuit de travail, « aujourd'hui » et la page parlent de la nuit commencée la veille.
4. **Durées.** Une tâche sans durée n'est plus placée avec 30 minutes supposées : elle est rendue « à estimer ». Lorakus demande la durée, ou propose son estimation si on la lui demande ; la carte (`assistant.set_estimate`) dit laquelle des deux. `core_tasks.estimate_source` garde l'origine (`user` ou `assistant`). Une tâche d'un module garde la même durée que son objet : l'événement `planning.task_estimated` prévient le module (academic met à jour l'évaluation).
5. **Temps réel.** À la fin d'une tâche, le temps réellement passé peut être donné (carte du chat, fenêtre de la page Cours) : `core_tasks.actual_minutes`. Avec l'origine des estimations, il permettra de mesurer l'écart entre prévu et réel. Aucune prédiction n'est faite avant d'avoir des données : c'est le préalable d'un éventuel modèle (P16), pas un modèle.
6. **Plus de plafond caché.** Les 6 h par jour disparaissent : la plage dite par l'utilisateur est la seule limite.
7. **Ce que fait le modèle, ce que fait le code.** Le modèle comprend la phrase (« je bosse de 15 h à 3 h, je mange vers 22 h ») et l'explique ensuite (le matin, l'après-midi) ; il lit le plan par `assistant.plan_today`. Le code valide le cadre, écrit la carte et calcule le plan. Le modèle ne place jamais un créneau lui-même.

La table `core_planning_preferences` est supprimée par la migration 0015, avec l'accord du propriétaire (elle ne contenait que des essais). Le retour arrière la recrée vide.

## Amendement du 2026-11-21 (PR 50) : étapes d'une tâche

- **Rang des étapes** : `core_tasks.step_number` (migration 0016), seulement pour une sous-tâche (1 à 20). Le découpage du Sergent (`focus.split_task`) crée les étapes dans une même transaction : leur date de création ne dit pas leur ordre, le rang si.
- **Planificateur** : une tâche qui a été découpée n'est plus placée elle-même, même quand toutes ses étapes sont faites (il reste à la marquer terminée, pas à refaire tout le travail) ; les étapes d'une tâche restent ensemble, dans leur ordre, avec l'échéance et la priorité de la tâche quand elles n'en ont pas.
- **Fin d'une tâche de module** : `ModuleTasks.complete` termine aussi ses étapes encore ouvertes, comme `complete_task` le fait déjà quand l'utilisateur termine une tâche. Sans cela, finir un devoir découpé depuis la page Cours aurait laissé ses étapes au planning.
- `TaskView.subtasks` : toutes les sous-tâches, terminées comprises, à côté de `open_subtasks`.
