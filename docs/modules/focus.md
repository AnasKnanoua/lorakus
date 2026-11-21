# Module Sergent (`focus`)

Le Sergent est le premier spécialiste réel de Lorakus (ADR 0025 et 0026). Il répond à « qu'est-ce que je dois faire aujourd'hui ? » et « qu'est-ce que je dois rendre ? » par un **rapport** calculé par des règles, que le Majordome (module `assistant`) reçoit avec la question. Le modèle répond en un seul appel, en citant les sources du rapport, sans relire la journée par un outil. Le module découpe aussi une tâche longue en étapes, avec une carte de confirmation.

Il n'a aucune table : il lit le planning du Core (tâches, agenda, journée donnée par l'utilisateur, plan proposé), sous la RLS de l'utilisateur, à travers la même vue que la page « Ma journée ».

## Ce que fait le module

- **`day_plan`** : la journée en cours. Faits, par ordre d'importance : la journée telle que l'utilisateur l'a dite, les retards (3 au plus), le plan proposé et les créneaux horaires de l'agenda dans l'ordre du temps, puis les tâches sans durée (2 au plus). Le résumé dit combien de travail est proposé, ce qui est en retard, sans durée ou sans place.
- **`deadlines`** : les retards, puis les échéances des sept prochains jours, avec leur durée estimée ou « durée inconnue ».
- **Une seule question, et seulement si elle change le résultat** : sans journée dite et avec du travail ouvert, « Quand comptes-tu travailler aujourd'hui ? » ; avec une journée encore ouverte, la durée de la tâche la plus urgente qui n'en a pas. Le Majordome la pose telle quelle. Pas de réponse par défaut : le planificateur ne suppose ni heure ni durée (PR 49), le Sergent non plus. La roadmap prévoyait une réponse par défaut tirée de l'historique ; elle est écartée tant que l'historique ne dit rien de fiable (les horaires du propriétaire changent tous les jours).
- **Découper une tâche** (`focus.split_task`) : 2 à 8 étapes ordonnées, avec une durée par étape si elle est connue. Les étapes sont des sous-tâches du Core (`step_number` garde l'ordre) ; le planificateur les place à la place de la tâche, dans leur ordre, avec l'échéance et la priorité de la tâche.

Non couvert pour l'instant : présenter la journée le matin (briefing, PR 53) ; le palier 3 du routage (petit appel au modèle quand c'est ambigu) ; le cache des rapports (inutile : un rapport se calcule en quelques millisecondes).

## Prendre les devants (P5, ADR 0042)

- **Règle** (`watch.py`, job `focus.deadline_watch` toutes les 10 minutes, un seul pour tous les utilisateurs qui ont le Sergent activé) : une tâche ouverte à rendre dans 3 jours ou moins (jour local du compte), sans étape terminée, donne **un** signal `focus.deadline_soon`. Clé : la tâche et son échéance (une échéance déplacée est une nouvelle cause). Une étape d'une tâche ne donne pas de signal : sa tâche suffit.
- **Retrait** : tâche commencée (une étape terminée), repoussée au-delà de 3 jours, terminée ou supprimée ; module désactivé. La carte disparaît.
- **Textes**, écrits par le code : « À rendre dans 3 jours » ; « CSEC507 : rapport · jeudi 26 novembre 2026. Pas encore commencé. » ; pour la notification : « Toujours pas commencé : « … » est à rendre dans 3 jours (jeudi 26 novembre 2026). Il te faut environ 3 h. Ouvre Ma journée pour lui trouver un créneau. » Faits pour « Pourquoi ? » : tâche, échéance (source : Cours, Projets ou Tâches), avancement, durée estimée (« estimé » si c'est Lorakus qui l'a proposée).
- **Ce que le Sergent ne fait pas** : il ne notifie jamais lui-même. La politique du Core montre une carte, puis une notification seulement si la carte n'a pas été vue en 24 h, pendant la plage de travail du jour (scénario 4).
- **Limite assumée** : sans découpage, Lorakus ne voit pas qu'une tâche est commencée. « OK » sur la carte suffit : rien d'autre ne suivra.

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Contenu du rapport (plan, retards, échéances) | Règles (vue du jour du Core) | Exact, gratuit, en quelques millisecondes, reproductible ; le même plan que la page |
| Choisir la question à poser | Règle (journée manquante, puis durée de la tâche la plus urgente) | Une seule question, toujours la même pour la même situation |
| Reconnaître une question pour le Sergent | Mots-clés (palier 1), puis similarité avec des exemples par le modèle d'embeddings local (palier 2) | Aucun appel au modèle ; rien ne sort du serveur ; mesuré sur un jeu distinct |
| Proposer un découpage | LLM, dans l'appel déjà fait pour la réponse | Langage naturel ; le code vérifie tout et la carte attend le clic |
| Formuler la réponse | LLM | Le rapport est une donnée ; le modèle l'explique et cite ses sources |
| Rappeler une échéance proche | Règle (3 jours, aucune étape terminée), puis politique d'intervention du Core | Un seul rappel, explicable, sans appel au modèle : il part même si le fournisseur d'IA est coupé |
| Durée d'un devoir sans estimation | Rien : on la demande | Pas assez de temps réels enregistrés (PR 49) pour estimer ; ML en P16 |

## Rapports

Chaque fait porte une source lisible et dit s'il est mesuré ou estimé :

| Fait | Source | Mesuré |
| --- | --- | --- |
| Ta journée | « Ta journée, telle que tu l'as dite » | oui |
| Retard, échéance, durée inconnue | « Tâche « … » », ou « Cours « … » » pour une tâche du module `academic` | oui |
| Créneau de l'agenda | « Agenda (calendrier importé) » | oui |
| Créneau proposé | « Plan calculé par Lorakus (règles) » | non : c'est une proposition |

Le rapport respecte le contrat (ADR 0026) : 3 phrases au plus, 10 faits au plus, 1 500 caractères. Les faits sont ajoutés par ordre d'importance tant qu'il y a la place ; s'il en manque, le rapport est « partiel » et le résumé dit combien d'éléments ne sont pas détaillés. Un titre trop long est coupé. Heures dans le fuseau du compte, « (le lendemain) » après minuit.

## Routage

Mots-clés et exemples dans `lorakus_modules/focus/specialist.py`, écrits sur la partie `tuning` de `backend/tests/evals/sergent_routing.json`. La partie `measure` a été écrite avant eux et ne sert qu'à mesurer ; on ne retouche pas le profil en regardant ses erreurs. Objectif fixé avant mesure : 90 % de bonnes décisions sur `measure`, avec le vrai modèle (job de la CI).

Première mesure (2026-11-21, sans le vrai modèle) : mots-clés seuls, 22/22 sur `tuning` et 16/22 (0,727) sur `measure`. Le sens n'est consulté que si aucun mot-clé ne correspond ; son apport se lit dans le résumé du job de la CI. Une question mal routée n'est pas une erreur grave : sans rapport, le modèle lit la journée par l'outil du plan du jour (un appel de plus), et un rapport de trop ne coûte que quelques centaines de caractères dans le prompt.

## Outil du chat

| Outil | Risque | Effet |
| --- | --- | --- |
| `focus.split_task` | `write` | Carte « Découper « … » en 3 étapes : 1. … (30 min) / … / Total : 3 h 30 (estimation de Lorakus) / Durée prévue pour la tâche : 3 h / Échéance des étapes : … » ; le clic crée les étapes (provenance `conversation:<id>`) |

Ajouté à `CHAT_TOOLS` après revue (ADR 0040, amendement du 2026-11-21) ; proposé au modèle seulement si le module est activé. Refusés **avant toute carte** : tâche inconnue, terminée, déjà découpée, ou qui est elle-même une étape ; titres vides, invisibles ou en double (casse ignorée) ; moins de 2 ou plus de 8 étapes ; durée hors bornes ; champ inconnu.

## Sécurité

- Aucune table, aucune écriture hors de l'outil : le rapport est une lecture, sous la RLS de l'utilisateur (`open_transaction` du Core).
- Classe maximale des rapports : `personal`. Aucun fait `sensitive` ; le module ne voit ni la mémoire ni de données bancaires.
- Le rapport entre dans le prompt comme une donnée, dans un bloc qu'il ne peut pas refermer, chaque ligne passée par `inert()` (titres de tâches et de créneaux venus de calendriers externes). Corpus d'injections, position 8 : chaque attaque dans un créneau de l'agenda et un titre de tâche, face à un modèle qui obéit ; rien ne change sans clic.
- L'heure de la question est donnée par le Core (`SpecialistContext.now`) : le Sergent ne lit jamais l'horloge lui-même.

## Activer

Page des modules : « Sergent ». Désactivé, il n'est jamais consulté et son outil n'est pas proposé au modèle.

## Tests

`tests/unit/test_sergent_reports.py` (rapports sans base : faits, sources, question, nuit, jour sans travail, rapport partiel, fuseau), `tests/integration/test_sergent.py` (scénario 1 de bout en bout : routage, rapport dans le prompt, un seul appel au modèle, trace ; question unique ; échéances ; module désactivé ; isolation entre utilisateurs ; spécialiste en panne ; découpage par carte, refus, ordre des étapes dans le plan, étapes closes avec le devoir), `tests/evals/test_sergent_routing.py` (routage mesuré), corpus d'injections (position 8), banc du vrai modèle (4 cas, non encore mesurés).
