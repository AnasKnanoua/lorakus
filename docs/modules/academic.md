# Module Cours (`academic`)

Cours et évaluations (devoirs, examens). Chaque évaluation crée **sa tâche** dans le planning du Core (ADR 0018) : c'est elle que voient la liste des tâches, l'assistant et, à partir de la PR 47, le planificateur. Le module ne garde que le sens métier : à quel cours appartient le travail, si c'est un devoir ou un examen, son coefficient.

## Ce que fait le module

- **Cours** : un nom (80 caractères), comparé sans casse ni accents (« Réseaux » et « reseaux » sont le même cours). 50 au plus. Supprimer un cours supprime ses évaluations et leurs tâches.
- **Évaluations** : type (`assignment` ou `exam`), titre (110 caractères), **échéance obligatoire** (un jour local), durée estimée et coefficient facultatifs. 200 ouvertes au plus ; jamais deux évaluations ouvertes du même cours avec le même titre (casse ignorée) et la même échéance.
- **Tâche de l'évaluation** : créée par le port `ModuleTasks("academic")`, `owner_ref` = identifiant de l'évaluation, titre « cours : titre », même échéance et même durée. Corriger l'évaluation met la tâche à jour ; la supprimer la supprime. Tout se fait dans la même transaction : jamais d'évaluation sans tâche, ni l'inverse.
- **Terminer, dans les deux sens** :
  - depuis la page, après une fenêtre de confirmation (terminer ne se défait pas), l'évaluation et sa tâche sont terminées ensemble (par le port : aucun événement en retour) ;
  - depuis le chat, l'utilisateur termine la **tâche** (carte) ; le Core publie `planning.task_completed` dans la même transaction, et le worker livre l'événement au module, qui termine l'évaluation (le relais du worker passe toutes les 2 secondes au repos).
- **Retards** : une évaluation ouverte est en retard quand son jour d'échéance est passé (à rendre aujourd'hui : pas encore en retard). « Aujourd'hui » est calculé par le serveur dans le fuseau du compte, jamais par la page ni à l'heure du serveur.

Non couvert pour l'instant (aucun consommateur) : renommer un cours, rouvrir une évaluation terminée, rappels à J-3 (signaux, P5), durée par défaut d'après les devoirs passés (PR 47 et 48).

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Comprendre « le devoir de ML pour vendredi, environ 3 h » | LLM du chat, qui appelle l'outil | Langage naturel ; la date qu'il a comprise s'affiche en entier sur la carte avant tout clic |
| Texte de la carte, cours existant ou nouveau, doublon, date passée | Règles (code de l'outil) | Ce que l'utilisateur confirme ne dépend d'aucun texte du modèle |
| Retards, jours restants | Règle (date locale du compte) | Exact, gratuit, testable autour de minuit |
| Retrouver un cours par son nom | Règle (clé sans casse ni accents) | Prévisible ; un nom inconnu est annoncé « nouveau cours » sur la carte plutôt que deviné |
| Durée par défaut d'un devoir | Rien pour l'instant ; médiane des durées passées du même cours quand le planificateur en aura besoin, ML en P16 | Pas de données aujourd'hui |

## Outil du chat

| Outil | Risque | Effet |
| --- | --- | --- |
| `academic.add_assessment` | `write` | Carte « Ajouter un devoir : « … » / Cours : … / Échéance : vendredi 20 novembre 2026 (demain) » ; le clic crée le cours s'il manque, puis l'évaluation et sa tâche (provenance `conversation:<id>`) |

Ajouté à `CHAT_TOOLS` après revue (ADR 0040, amendement du 2026-11-20) ; proposé au modèle seulement si le module est activé. Refusés **avant toute carte** : échéance absente (schéma), passée ou à plus de 5 ans, évaluation ouverte identique, cours de trop. La carte écrit « (nouveau cours) » quand le nom ne correspond à aucun cours : une faute dans le nom se voit avant le clic. Lire, terminer ou supprimer passe par les outils des tâches de l'assistant (une tâche d'un module ne se supprime pas depuis le chat).

## Événement consommé

| Événement | Émis par | Effet |
| --- | --- | --- |
| `planning.task_completed` (`task_id`, `owner_module`, `owner_ref`) | Le Core, quand l'**utilisateur** termine une tâche créée par un module | Si `owner_module` vaut `academic` : l'évaluation `owner_ref` est terminée, à l'instant où la tâche l'a été |

L'événement n'est qu'un signal : le handler relit la tâche par le port et n'agit que si elle existe, appartient au module et est terminée. Un événement rejoué, forgé, d'un autre module ou d'un autre utilisateur (RLS) ne change rien. Le handler agit même si le module est désactivé : désactiver ne supprime pas les données, elles doivent rester justes au retour.

## Sécurité

- RLS forcée sur les deux tables ; une évaluation est liée à son cours par une clé composée (cours, utilisateur) : elle ne peut pas viser le cours d'un autre, même en connaissant son identifiant.
- Noms et titres ramenés à une ligne visible (caractères invisibles et de contrôle retirés) : ils ne peuvent pas imiter une ligne de la carte. Ils n'atteignent le modèle que par le titre de leur tâche, dans le résultat de l'outil de liste (une donnée).
- Contraintes de la base écrites pour ne jamais valoir NULL ; `completed_at` présent si et seulement si l'évaluation est terminée ; provenance obligatoire pour une évaluation venue du chat.
- Journal d'audit : identifiants seulement, jamais un nom de cours ni un titre.
- Corpus d'injections, position 6 : chaque attaque dans un nom de cours et un titre d'évaluation, face à un modèle qui obéit ; rien ne change sans clic.

## Données

| Table | Classe | Contenu |
| --- | --- | --- |
| `acad_courses` | `personal` | Nom, clé de comparaison |
| `acad_assessments` | `personal` | Cours, type, titre, échéance, coefficient, durée estimée, statut, provenance |

Les tâches sont dans `core_tasks` (Core, `owner_module = 'academic'`). Export « Mes données » : cours et évaluations ; les tâches avec le planning du Core.

## API (`/api/v1/academic`, session exigée, module activé)

| Route | Effet |
| --- | --- |
| `GET /courses` | Cours par ordre alphabétique, avec leur nombre d'évaluations ouvertes |
| `POST /courses` | `{name}` ; 422 avec un message lisible (doublon, limite, nom vide) |
| `DELETE /courses/{id}` | Supprime le cours, ses évaluations et leurs tâches (204) |
| `GET /assessments?state=open\|done` | Ouvertes par échéance, ou terminées (les plus récentes d'abord) ; chaque ligne porte `overdue` et `days_left`, calculés dans le fuseau du compte |
| `POST /assessments` | `{course_id, kind, title, due_on, weight?, estimate_minutes?}` ; une échéance passée est acceptée (devoir déjà en retard), pas une date à plus d'un an en arrière ou de 5 ans en avant |
| `PUT /assessments/{id}` | Corrige une évaluation ouverte (tout le contenu ; un champ absent est retiré) |
| `POST /assessments/{id}/complete` | Termine l'évaluation et sa tâche |
| `DELETE /assessments/{id}` | Supprime l'évaluation et sa tâche (204) |

## Page `/academic`

Voir `docs/frontend.md` (« Écrans »). Entrée « Cours » de la barre latérale, groupe `tools`.

## Tests

`tests/integration/test_academic.py` (service sous RLS : cours, tâche créée par le port, corrections, retards, événement de bout en bout avec le relais du worker, événements faux ou rejoués, suppression, isolation à deux utilisateurs, contraintes de la base), `tests/integration/test_academic_api.py` (routes, fuseau, module désactivé, export, carte du chat et critère « terminer la tâche termine le devoir »), corpus d'injections (position 6), banc du vrai modèle (3 cas, non encore mesurés), `frontend/src/features/academic/academic.test.tsx` (page, accessibilité).
