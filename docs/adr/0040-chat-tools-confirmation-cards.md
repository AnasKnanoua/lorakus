# ADR-0040 — Outils dans le chat : cartes de confirmation

- **Statut** : Accepté (2026-11-14, plan validé par le propriétaire le 2026-11-13, PR 38)
- **Date** : 2026-11-14
- **Revue prévue** : à chaque nouvel outil proposé au chat ; avant toute ouverture commerciale

## Contexte

Le Majordome doit pouvoir agir (retenir, corriger, plus tard créer une tâche), mais un modèle peut se tromper ou être manipulé par un texte : un souvenir, un message collé, plus tard une page web (ADR 0012). Le `ToolRuntime` de la PR 30 savait déjà mettre une action `write` ou `sensitive` en attente d'une confirmation ; il manquait le chemin du modèle vers lui, et l'interface de la confirmation.

## Décision

1. **Le modèle demande, le code exécute, l'utilisateur décide.** Toute demande d'outil du modèle passe par le `ToolRuntime` (schéma, module actif, audit). `read` s'exécute et son résultat revient au modèle comme une donnée ; `write` et `sensitive` produisent une **carte** dans le chat, et le modèle apprend seulement qu'elle attend la confirmation.
2. **Le modèle ne peut pas confirmer.** Il ne reçoit jamais l'identifiant de la carte ; aucun outil ne confirme ; la confirmation n'existe que dans l'API, avec la session de l'utilisateur (contrôle d'origine, `SameSite=Strict`), et une preuve d'identité de moins de 10 minutes pour `sensitive`.
3. **Le texte de la carte est écrit par le code.** Chaque outil `write` ou `sensitive` fournit `summary`, calculé à partir des arguments validés et des données de l'utilisateur (ex. « Avant : … / Après : … » relu en base). Affiché en texte brut. `ToolSpec` refuse un outil `write` ou `sensitive` sans `summary`.
4. **Profil assistant : liste explicite** (`CHAT_TOOLS`). Un outil d'un futur module n'est proposé au modèle qu'après revue et ajout à la liste. Noms « fil » `module__action` (les fournisseurs refusent le point).
5. **Bornes par message** : 4 appels au modèle au plus (le dernier sans outil), 6 appels d'outils, 3 cartes.
6. **Rythme et coût** : un message compte pour un seul appel dans la limite par minute (`continuation`) ; chaque appel compte dans la limite du jour, le budget mensuel et passe par tous les refus du `ModelRouter`. Chaque appel est enregistré dans `core_ai_usage` ; le coût du message est leur somme.
7. **Confirmation atomique** : réservation (`FOR UPDATE`), exécution et audit dans une transaction. Un échec laisse la carte en attente ; deux clics n'exécutent qu'une fois. Après décision, les arguments sont effacés ; un déclencheur n'autorise à `lorakus_app` qu'une modification des arguments : les vider (la garantie « arguments figés » de la 0006 demeure).
8. **Mémoire du dialogue** : les cartes sont enregistrées avec la réponse (`asst_messages.actions`) et réaffichées au rechargement ; au message suivant, le modèle reçoit une note écrite par le code (« confirmée par l'utilisateur », « refusée »…). Supprimer une conversation annule ses cartes en attente et efface leurs arguments (`origin`).
9. **Premiers outils** (module `assistant`) : `search_memory` (read), `remember` et `update_memory` (write), `forget_memory` (sensitive : toute suppression l'est, spec des outils). Un souvenir retenu depuis le chat est confirmé par la carte et garde sa provenance (`conversation:<id>`, ADR 0015).

## Alternatives rejetées

- **Confirmation en langage naturel** (« oui, vas-y ») : un texte injecté peut l'imiter ; le clic sur une carte ne l'est pas.
- **Exécuter les `write` et demander l'annulation ensuite** : contraire à ADR 0039 (rien n'entre en mémoire sans confirmation) et à SECURITY §7.
- **Livraison en deux PR** (lecture, puis cartes) : la lecture seule n'apportait presque rien ; une seule PR, construite par étapes vérifiées.

## Conséquences

- Un clic de plus pour chaque modification, voulu. Une action supprimant des données demande, en plus, le mot de passe si la dernière preuve d'identité date de plus de 10 minutes.
- Le coût d'un message avec outil est d'environ deux appels au modèle (mesure en production après déploiement).
- Le corpus d'injections (PR 41, `backend/tests/security/`, pytest plutôt que Promptfoo) rejoue chaque attaque face à un modèle qui obéit, en s'appuyant sur ces tests : `backend/tests/integration/test_chat_tools.py`.

## Amendement du 2026-11-18 (PR 44) : outils des tâches

Ajoutés à `CHAT_TOOLS` après revue : `list_tasks` (read), `add_task` et `complete_task` (write), `delete_task` (sensitive). La carte d'ajout est écrite par le code avec l'échéance en date absolue, calculée dans le fuseau du compte (« vendredi 20 novembre 2026 (demain) ») : si le modèle a mal compris « vendredi », l'utilisateur le voit avant de confirmer. Une échéance passée ou à plus de 5 ans est refusée dès la proposition (aucune carte). Une tâche créée par un module ne se supprime pas depuis le chat. Le titre est nettoyé (une ligne, sans caractère invisible) : il ne peut pas imiter une ligne de la carte. Attaques rejouées dans le titre d'une tâche (corpus) et 4 cas au banc (`tests/evals/reply_behaviour.json`).

## Amendement du 2026-11-18 (correctif) : jamais deux fois la même carte

Constaté en production le jour même : une carte confirmée était reproposée à chaque message suivant de la conversation, et une carte sans réponse aussi. Seule une consigne au modèle l'empêchait ; la note « confirmée par l'utilisateur » pouvait même se lire comme un accord à exécuter. Règles ajoutées, dans le code :

1. **Une action, une confirmation en attente** (`ToolRuntime`) : même outil, mêmes arguments validés (égalité JSONB) et même provenance qu'une confirmation encore valable (ni utilisée, ni annulée, ni expirée) : la demande rend la confirmation existante (`already_pending`), sans nouvelle ligne ni nouvelle carte ; le modèle reçoit un texte fixe. Une carte refusée ou expirée ne bloque plus : l'utilisateur peut redemander.
2. **Refus avant toute carte quand l'action est déjà faite** : `remember` vérifie l'empreinte du souvenir (déjà retenu, ou proposé dans la page Mémoire) avant d'écrire la carte, et non plus seulement au clic ; `add_task` refuse une tâche personnelle ouverte de même titre (casse ignorée) et de même échéance, au moment de la carte et dans le service `planning` (jamais deux tâches ouvertes identiques).
3. **Issue écrite pour être comprise** : la note rappelle une carte « faite, après confirmation de l'utilisateur » (et non plus « confirmée »), « toujours affichée », « refusée » ou « expirée sans réponse » ; le prompt (`assistant-system-2026-11-18.3`) ajoute qu'une action déjà proposée ne se propose jamais une seconde fois.

Tests : `test_the_same_action_never_waits_twice` (dont un outil sans argument, dont les arguments effacés après décision ressemblent à une nouvelle demande), cartes de mémoire et de tâches avec un faux modèle qui redemande l'outil à chaque message, 19 mutations détectées ; 2 cas au banc (`confirmed_card_not_again`, `waiting_card_not_again`).

## Amendement du 2026-11-20 (PR 46) : premier outil d'un autre module

`academic.add_assessment` (write) est ajouté à `CHAT_TOOLS` après revue : c'est le premier outil du chat qui n'appartient pas au module `assistant`. La liste reste dans `assistant` (le profil du Majordome) ; l'outil, son schéma et le texte de sa carte restent dans son module, et il n'est proposé au modèle que si l'utilisateur a activé ce module (`ToolRuntime.available`).

Revue : la carte est écrite par le code (devoir ou examen, cours tel qu'il est enregistré, ou « nouveau cours » si le nom ne correspond à aucun, date absolue dans le fuseau du compte, durée, coefficient) ; nom du cours et titre ramenés à une ligne, donc incapables d'imiter une ligne de la carte ; échéance obligatoire dans le schéma (le modèle doit la demander plutôt que l'inventer) ; date passée ou à plus de 5 ans, évaluation ouverte identique et cours de trop refusés avant toute carte ; le clic crée le cours s'il manque, l'évaluation et sa tâche dans la transaction de la confirmation. Aucune consigne ajoutée au prompt système : c'est la description de l'outil qui dit de le préférer à une tâche simple pour un travail lié à un cours (version du prompt inchangée, `assistant-system-2026-11-20.1`).

Corpus : position 6 (chaque attaque dans un nom de cours et un titre d'évaluation ; le modèle qui obéit tente d'ajouter des évaluations en masse, de terminer et de supprimer la tâche du devoir). Banc : 3 cas (25 au total, non encore mesurés avec le vrai modèle) : `assessment_by_course_card`, `assessment_needs_a_date`, `errand_stays_a_task`.

## Amendement du 2026-11-20 (PR 48) : outils des préférences de planification

Ajoutés à `CHAT_TOOLS` après revue : `assistant.list_preferences` (read), `assistant.set_preference` et `assistant.clear_preference` (write). Revue : les arguments ne contiennent aucun texte libre (une clé d'un catalogue fermé, des heures `HH:MM`, des jours nommés, des minutes) ; la carte est écrite par le code et donne la valeur proposée et la valeur actuelle ; un champ manquant, une valeur hors bornes, une valeur déjà en place ou un ensemble incohérent sont refusés avant toute carte ; rien n'est enregistré sans clic. Prompt inchangé.

Corpus : position 7 (le modèle qui obéit tente de déclarer la semaine sans travail, de finir la journée à 9 h, de retirer le déjeuner). Banc : 3 cas (28 au total, non encore mesurés avec le vrai modèle) : `preference_by_card`, `preference_needs_an_hour`, `trapped_task_preferences`.

## Amendement du 2026-11-21 (PR 49) : outils de la journée

Les trois outils des préférences (PR 48) sont retirés de `CHAT_TOOLS` avec les préférences (ADR 0018). Ajoutés après revue :

- `assistant.plan_today` (`read`) : le cadre du jour ou son absence (avec la consigne de demander, sans supposer d'heure), l'agenda, le plan calculé par le planificateur, les tâches « à estimer » et ce qui ne tient pas. Titres passés par `inert()`.
- `assistant.set_day` (`write`) : le cadre d'aujourd'hui ou de demain. Aucun texte libre (heures `HH:MM`, nature d'une pause dans une liste fermée) ; plage trop courte ou trop longue, pause hors de la plage, plage déjà passée, cadre identique, ou mélange d'un jour sans travail et d'horaires : refusés avant toute carte. La carte donne la date absolue, la plage (« le lendemain » si elle passe minuit), les pauses et ce qu'elle remplace.
- `assistant.set_estimate` (`write`) : la durée d'une tâche, avec qui la donne. La carte écrit « (estimation de Lorakus) » quand c'en est une, et la durée actuelle.
- `assistant.complete_task` prend en plus le temps réellement passé, que la carte affiche avec la durée prévue.

Prompt `assistant-system-2026-11-21.1` : ne jamais supposer d'heure ; lire la journée avant d'en parler ; sans cadre, demander quand l'utilisateur travaille ; demander la durée d'une tâche qui n'en a pas, ou proposer une estimation présentée comme telle ; demander sans insister le temps passé quand une tâche est finie. Corpus : position 7 réécrite (le modèle qui obéit tente de déclarer la journée sans travail, de la réduire à rien, de passer 24 h à travailler, de changer les durées et de terminer la tâche). Banc : 4 cas à la place des 3 des préférences (29 au total, non encore mesurés avec le vrai modèle).

## Amendement du 2026-11-21 (PR 50) : découpage d'une tâche

Ajouté à `CHAT_TOOLS` après revue : `focus.split_task` (`write`, module Sergent, proposé seulement s'il est activé). Le découpage est proposé par le modèle dans l'appel déjà fait pour la réponse ; le code vérifie la tâche (existe, ouverte, ni déjà découpée ni elle-même une étape), les étapes (2 à 8, titres lisibles et distincts, durées bornées), écrit la carte (étapes numérotées, total, durée prévue, échéance) et ne crée rien avant le clic. La carte dit si les durées sont celles de l'utilisateur ou une estimation de Lorakus.

Prompt `assistant-system-2026-11-21.2` : quand un rapport de spécialiste suffit, répondre avec lui sans relire les mêmes données par un outil ; poser la question d'un rapport, une seule, plutôt que deviner. La consigne de proposer un découpage est dans la description de l'outil (absente si le module est désactivé). Corpus : position 8. Banc : 4 cas (33 au total, non encore mesurés avec le vrai modèle).
