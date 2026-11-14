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
- Le corpus d'injections Promptfoo (PR 41) s'appuiera sur ces tests : `backend/tests/integration/test_chat_tools.py`.
