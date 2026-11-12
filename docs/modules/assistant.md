# Module Assistant (`assistant`)

Le Majordome de l'ADR 0025, première version : une conversation avec l'assistant, réponse affichée au fil de l'eau. Sans outils, sans mémoire ni agenda pour l'instant (PR 36 à 39) ; le prompt système le dit au modèle, qui doit l'avouer plutôt qu'inventer.

## Ce que fait le module

- **Conversations** : créer, lister (les plus récentes d'abord), relire, supprimer. Le titre est le début du premier message (aucun appel IA).
- **Un tour** : le message de l'utilisateur est enregistré, puis la réponse arrive en flux (SSE). Elle est enregistrée même si l'utilisateur ferme l'application en cours de route (statut `interrupted`).
- **Repli** (scénario 8) : si l'IA ne peut pas répondre (plafond atteint, fournisseur en panne, coupure générale, erreur interne), la réponse est un **message de secours fixe**, enregistré avec le statut `fallback`. Ces messages ne sont jamais renvoyés au modèle.
- **Coût borné** : seuls les derniers messages tenant dans environ 6 000 tokens partent au modèle (environ 0,0006 $ d'entrée par message avec Haiku 5.5) ; un message fait au plus 8 000 caractères.

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Répondre | LLM (Haiku 5.5, via `ModelRouter`) | Langage naturel : seul un LLM le fait |
| Titre | Règle (début du message) | Gratuit, instantané, prévisible ; un titre par LLM coûterait un appel par conversation |
| Historique envoyé | Règle (budget de tokens) | Coût et latence bornés, sans résumé par LLM (viendra avec la mémoire si utile) |
| Messages de secours | Gabarits fixes | Doivent marcher précisément quand l'IA ne marche pas |

## API (`/api/v1/assistant`, session et module activé requis)

| Méthode et chemin | Rôle |
| --- | --- |
| `GET /conversations` | Les 100 conversations les plus récentes |
| `POST /conversations` | Nouvelle conversation (201) |
| `GET /conversations/{id}` | Conversation et messages |
| `DELETE /conversations/{id}` | Suppression définitive (204) |
| `POST /conversations/{id}/messages` | Corps `{"content": "..."}` ; réponse `text/event-stream` |

Flux de réponse :

```
event: delta
data: {"text": "Bon"}

event: delta
data: {"text": "jour"}

event: done
data: {"message_id": "…", "status": "ok", "budget_warning": false}
```

`status` vaut `ok`, `interrupted` ou `fallback`. `budget_warning` passe à `true` quand le plafond mensuel est consommé à 80 %.

## Configuration (par utilisateur, `PUT /api/v1/modules/assistant`)

| Clé | Défaut | Rôle |
| --- | --- | --- |
| `display_name` | `Lorakus` | Nom sous lequel l'assistant se présente (une ligne, sans balisage) |
| `timezone` | `Europe/Paris` | Fuseau de la date et de l'heure données au modèle |

## Données et sécurité

- Tables `asst_conversations` et `asst_messages`, classe `personal`, RLS forcée. Clé étrangère composée (conversation, utilisateur) : un message ne peut pas viser la conversation d'un autre, même en connaissant son identifiant.
- Classe `personal` : uniquement vers un fournisseur payant (ADR 0007, D-D). Aucun contenu de conversation dans les journaux ni dans les métriques.
- Prompt système versionné (`prompts.py`, `PROMPT_VERSION`), enregistré avec chaque réponse.
- Réponses en `Cache-Control: no-store`.

## Exploitation

Métrique `lorakus_assistant_replies_total{status, reason}` ; alertes et procédures dans [le runbook du moteur IA](../runbooks/ai.md).
