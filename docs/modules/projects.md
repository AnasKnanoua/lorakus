# Module Projets (`projects`)

Boîte d'idées, projets et tâches de projet. Chaque tâche de projet crée **sa tâche** dans le planning du Core (ADR 0018), comme une évaluation du module Cours : c'est elle que voient « Ma journée », le planificateur, le Sergent et les outils des tâches du chat. Le module garde le sens métier : à quel projet appartient le travail, où en est le projet, depuis quand il dort, et les idées qui ne sont pas encore du travail.

## Ce que fait le module

- **Boîte d'idées** : une ligne (500 caractères), notée en un geste, sans échéance ni durée : une idée n'est pas du travail. 300 au plus dans la boîte ; jamais deux idées identiques (casse ignorée). Une idée s'**archive** (gardée, hors de la vue), se **supprime** (après confirmation), ou **devient un projet** : elle quitte alors la boîte et son texte devient la description du projet.
- **Projets** : nom (80 caractères, comparé sans casse ni accents, unique par utilisateur), description facultative (500). 20 projets actifs au plus : finir avant de commencer.
- **Tâches de projet** : titre (110 caractères), échéance et durée facultatives. 100 ouvertes au plus par projet ; jamais deux tâches ouvertes du même titre dans un projet. La tâche du planning est créée par le port `ModuleTasks("projects")`, `owner_ref` = identifiant de la tâche de projet, titre « Projet : titre » ; tout se fait dans la même transaction. Sans durée, la tâche n'entre pas dans le plan du jour (PR 49) : Lorakus demande ou estime la durée, il ne la suppose pas.
- **Terminer, dans les deux sens** : depuis la page (fenêtre de confirmation, temps passé facultatif), la tâche de projet et sa tâche du planning sont terminées ensemble par le port ; depuis le chat, l'utilisateur termine la **tâche** du planning, le Core publie `planning.task_completed` et le worker livre l'événement au module, qui termine la tâche de projet.
- **Terminer un projet** : ses tâches ouvertes sont terminées avec lui (ici et dans le planning, étapes du Sergent comprises), après une confirmation qui dit combien. **Supprimer un projet** supprime ses tâches et leurs tâches du planning.
- **Projets qui dorment** : un projet actif sans activité depuis 14 jours ou plus (`IDLE_DAYS`). L'activité, c'est la création du projet, l'ajout d'une tâche et la fin d'une tâche (depuis la page ou le chat, à l'instant où la tâche a été terminée). La page affiche « Sans activité depuis N jours » ; la carte « Commencer un projet » rappelle les projets qui dorment ; l'outil de liste les signale au modèle. Les projets actifs sont triés de celui qui a le moins bougé (le plus exposé à l'oubli) à celui qui a bougé en dernier ; les terminés, du plus récent au plus ancien.

Non couvert pour l'instant (aucun consommateur) : renommer un projet ou une tâche, rouvrir, désarchiver une idée, rappel proactif d'un projet qui dort (signaux, P5), découpage d'une tâche de projet par le Sergent depuis la page (il passe par le chat, `focus.split_task`).

- **Capture par Telegram** (PR 54) : le module fournit le port `capture` du Core (`capture.py`). Un message envoyé au bot lié devient une idée de la boîte, provenance `telegram` (migration `projects_0002`, contrainte `ck_proj_ideas_source` ; la descente les range en `user`), sans carte ; mêmes règles que la page (500 caractères, pas de doublon, 300 au plus), refus renvoyés tels quels au bot. Le texte n'est jamais lu par un modèle à la réception ; l'outil de liste le rend par `inert()`.

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Comprendre « j'ai une idée… », « je me lance dans… », « ajoute … à mon projet X » | LLM du chat, qui appelle l'outil | Langage naturel ; la carte montre ce qui sera créé avant tout clic |
| Idée ou projet ? | Consigne de l'outil (une idée tant que l'utilisateur ne dit pas s'y mettre), vérifiée par le banc | Un mauvais choix ne coûte qu'un refus de la carte |
| Projet qui dort, avancement, retards | Règles (horloge du serveur, fuseau du compte) | Exact, gratuit, testable |
| Retrouver un projet par son nom | Règle (clé sans casse ni accents) | Un nom inconnu est refusé avant toute carte, avec un message lisible |
| Durée d'une tâche | Donnée par l'utilisateur ; sinon demandée ou estimée par Lorakus (PR 49) ; ML en P16 quand il y aura des temps réels | Pas de données aujourd'hui |

## Outils du chat

| Outil | Risque | Effet |
| --- | --- | --- |
| `projects.list` | `read` | Projets actifs (nom, but, tâches ouvertes et faites, jours sans activité s'ils dorment) et dernières idées, tous les textes neutralisés par `inert()` |
| `projects.add_idea` | `write` | Carte « Noter une idée : « … » » |
| `projects.add_project` | `write` | Carte « Commencer le projet « … » / But / 1. … » (8 premières tâches au plus), avec « Projets qui dorment : … » quand il y en a |
| `projects.add_task` | `write` | Carte « Ajouter au projet « … » : « … » », échéance en entier et durée s'il y en a |

Ajoutés à `CHAT_TOOLS` après revue (ADR 0040, amendement du 2026-11-21) ; proposés au modèle seulement si le module est activé. Refusés **avant toute carte** : idée déjà dans la boîte, projet de même nom, trop de projets, tâches en double, projet inconnu ou terminé, échéance passée (le chat ; la page accepte une tâche déjà en retard). Terminer ou supprimer une tâche passe par les outils des tâches de l'assistant.

## Événements consommés

| Événement | Émis par | Effet |
| --- | --- | --- |
| `planning.task_completed` (`task_id`, `owner_module`, `owner_ref`) | Le Core, quand l'**utilisateur** termine une tâche créée par un module | Si `owner_module` vaut `projects` : la tâche de projet `owner_ref` est terminée, et le projet a bougé |

Comme pour Cours : l'événement n'est qu'un signal, relu par le port ; rejoué, forgé, d'un autre module ou d'un autre utilisateur, il ne change rien. Le handler agit même si le module est désactivé.

## Sécurité

- RLS forcée sur les trois tables ; une tâche est liée à son projet par une clé composée (projet, utilisateur).
- Textes ramenés à une ligne visible (caractères invisibles et de contrôle retirés) : ils ne peuvent pas imiter une ligne de carte. Ils n'atteignent le modèle que neutralisés par `inert()` (déplacé dans le Core, `lorakus/core/tools/inert.py`, pour que les modules l'utilisent sans importer l'assistant).
- Contraintes de la base écrites pour ne jamais valoir NULL ; dates de fin et d'archivage présentes si et seulement si le statut le dit ; provenance obligatoire pour ce qui vient du chat.
- Journal d'audit : identifiants seulement.
- Corpus d'injections, position 9 : chaque attaque dans une idée, un nom de projet et un titre de tâche, face à un modèle qui obéit ; rien ne change sans clic.

## Données

| Table | Classe | Contenu |
| --- | --- | --- |
| `proj_ideas` | `personal` | Texte, statut (boîte ou archivée), provenance |
| `proj_projects` | `personal` | Nom, clé de comparaison, description, statut, dernière activité, fin |
| `proj_tasks` | `personal` | Projet, titre, statut, fin, provenance |

Échéance et durée vivent sur la tâche du planning (`core_tasks`, `owner_module = 'projects'`), lues par `ModuleTasks.many` (une requête pour toute la liste). Export « Mes données » : idées, projets, tâches.

## API (`/api/v1/projects`, session exigée, module activé)

| Route | Effet |
| --- | --- |
| `GET /ideas?state=inbox\|archived` | Idées de la boîte, les plus récentes d'abord ; archivées, les plus récemment archivées d'abord |
| `POST /ideas` | `{text}` ; 422 lisible (doublon, limite, texte vide) |
| `POST /ideas/{id}/archive` | Archive l'idée |
| `DELETE /ideas/{id}` | Supprime l'idée (204) |
| `GET /projects?state=active\|done` | Projets avec leurs tâches (ordre de création), compteurs, `idle_days` (null s'il ne dort pas) ; chaque tâche porte `due_on`, `overdue`, `estimate_minutes` |
| `POST /projects` | `{name, description?, idea_id?}` ; depuis une idée, elle quitte la boîte et devient la description |
| `POST /projects/{id}/finish` | Termine le projet et ses tâches ouvertes |
| `DELETE /projects/{id}` | Supprime le projet et ses tâches (204) |
| `POST /projects/{id}/tasks` | `{title, due_on?, estimate_minutes?}` |
| `POST /tasks/{id}/complete` | `{actual_minutes?}` ou corps vide ; termine la tâche et sa tâche du planning |
| `DELETE /tasks/{id}` | Supprime la tâche et sa tâche du planning (204) |

## Page `/projets`

Voir `docs/frontend.md` (« Écrans »). Entrée « Projets » de la barre latérale, groupe `tools`.

## Tests

`tests/integration/test_projects.py` (service et routes sous RLS : idées, idée devenue projet, noms uniques et limites, tâches dans le planning, fin de projet, suppression, projet qui dort, fin depuis le chat par l'événement, événements forgés, autre utilisateur, module désactivé, export, contraintes de la base, liste neutralisée, cartes et refus), corpus d'injections (position 9), banc du vrai modèle (3 cas : idée et non projet, tâche de projet, projet piégé), `frontend/src/features/projects/projects.test.tsx` (page, accessibilité).
