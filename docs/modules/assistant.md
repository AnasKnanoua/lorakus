# Module Assistant (`assistant`)

Le Majordome de l'ADR 0025 : une conversation avec l'assistant, réponse affichée au fil de l'eau, avec les souvenirs confirmés (ADR 0039), les outils de mémoire (PR 38, ADR 0040), les tâches (PR 44) et la lecture de l'agenda (PR 45, ADR 0041).

## Ce que fait le module

- **Conversations** : créer, lister (les plus récentes d'abord), relire, supprimer. Le titre est le début du premier message (aucun appel IA).
- **Un tour** : le message de l'utilisateur est enregistré, puis la réponse arrive en flux (SSE). Elle est enregistrée même si l'utilisateur ferme l'application en cours de route (statut `interrupted`).
- **Repli** (scénario 8) : si l'IA ne peut pas répondre (plafond atteint, fournisseur en panne, coupure générale, erreur interne), la réponse est un **message de secours fixe**, enregistré avec le statut `fallback`. Ces messages ne sont jamais renvoyés au modèle.
- **Coût borné** : seuls les derniers messages tenant dans environ 6 000 tokens partent au modèle (environ 0,0006 $ d'entrée par message avec Haiku 5.5) ; un message fait au plus 8 000 caractères.

- **Outils** (PR 38, ADR 0040) : le modèle peut demander les outils de la liste `CHAT_TOOLS`. Tous passent par le `ToolRuntime` du Core. Au plus 4 appels au modèle par message (le dernier sans outil), 6 appels d'outils et 3 cartes. **Jamais deux fois la même carte** (correctif du 2026-11-18) : si le modèle redemande une action dont la carte attend encore (même outil, mêmes arguments, même conversation), aucune nouvelle carte n'apparaît et le modèle l'apprend par un texte du code ; un souvenir déjà connu ou déjà proposé, et une tâche ouverte de même titre et de même échéance, sont refusés avant toute carte. Au message suivant, chaque carte est rappelée au modèle avec son issue : « toujours affichée », « faite, après confirmation de l'utilisateur », « refusée » ou « expirée sans réponse ».

| Outil | Risque | Effet |
| --- | --- | --- |
| `assistant.search_memory` | `read` | Cherche dans les souvenirs confirmés (8 au plus) ; donne leurs identifiants |
| `assistant.remember` | `write` | Carte « Retenir : « … » » ; le clic crée un souvenir confirmé (provenance `conversation:<id>`) |
| `assistant.update_memory` | `write` | Carte « Avant / Après » ; le clic corrige le souvenir |
| `assistant.forget_memory` | `sensitive` | Carte « Oublier : « … » » ; le clic, avec une preuve d'identité récente, efface le souvenir |
| `assistant.list_agenda` | `read` | Créneaux de 1 à 14 jours (60 au plus), heures locales dans le fuseau du compte ; titres et lieux venus de calendriers externes passés par `inert()` (PR 45) |
| `assistant.plan_today` | `read` | La journée en cours (PR 49) : cadre ou son absence, agenda, plan calculé par le planificateur, tâches à estimer, ce qui ne tient pas ; titres passés par `inert()` |
| `assistant.set_day` | `write` | Carte « Ta journée du mercredi 18 novembre 2026 / Travail : de 15 h à 3 h (le lendemain) (12 h) / Repas : de 22 h à 22 h 45 » ; aujourd'hui ou demain ; bornes du Core (ADR 0018) |
| `assistant.set_estimate` | `write` | Carte « Durée de « … » : 2 h 30 (estimation de Lorakus) / Actuellement : aucune » ; l'origine de la durée est gardée |
| `academic.add_assessment` | `write` | Outil du module `academic` (PR 46), proposé seulement si ce module est activé : carte « Ajouter un devoir » ou « un examen », avec le cours et la date exacte ; voir `docs/modules/academic.md` |

## Approche (programmation classique, ML ou LLM)

| Besoin | Choix | Pourquoi |
| --- | --- | --- |
| Répondre | LLM (Haiku 5.5, via `ModelRouter`) | Langage naturel : seul un LLM le fait |
| Titre | Règle (début du message) | Gratuit, instantané, prévisible ; un titre par LLM coûterait un appel par conversation |
| Historique envoyé | Règle (budget de tokens) | Coût et latence bornés, sans résumé par LLM (viendra avec la mémoire si utile) |
| Messages de secours | Gabarits fixes | Doivent marcher précisément quand l'IA ne marche pas |
| Choisir un outil | LLM | Comprendre la demande ; l'exécution et la décision restent au code et à l'utilisateur |
| Texte des cartes | Règle (code de l'outil) | Ce que l'utilisateur confirme ne doit dépendre d'aucun texte du modèle |
| Choisir les spécialistes | Règles, puis similarité par embeddings locaux (marge réglée sur un jeu distinct) ; pas de LLM avant la P4 | Gratuit, rapide (environ 35 ms), rien ne sort du serveur ; un appel LLM coûterait 1,6 s |

## API (`/api/v1/assistant`, session et module activé requis)

| Méthode et chemin | Rôle |
| --- | --- |
| `GET /conversations` | Les 100 conversations les plus récentes |
| `POST /conversations` | Nouvelle conversation (201) |
| `GET /conversations/{id}` | Conversation et messages |
| `DELETE /conversations/{id}` | Suppression définitive (204) |
| `POST /conversations/{id}/messages` | Corps `{"content": "..."}` ; réponse `text/event-stream` |
| `GET /conversations/{id}/messages/{id}/trace` | « Pourquoi m'as-tu dit ça ? » (PR 39) : souvenirs fournis, outils et cartes, routage, spécialistes, modèle, appels, coût, classes transmises ; 404 pour une réponse antérieure |

Flux de réponse :

```
event: delta
data: {"text": "Bon"}

event: delta
data: {"text": "jour"}

event: tool
data: {"tool": "assistant.search_memory", "label": "A consulté ta mémoire", "ok": true}

event: card
data: {"confirmation_id": "…", "tool": "assistant.remember", "risk": "write", "summary": "Retenir : « … » (habitude)", "expires_at": "…", "status": "pending"}

event: done
data: {"message_id": "…", "status": "ok", "budget_warning": false}
```

Une carte se confirme par `POST /api/v1/tools/confirmations/{id}` (403 `reauth_required` pour une action sensible sans preuve d'identité récente, puis `POST /api/v1/auth/reauth`) et se refuse par `POST /api/v1/tools/confirmations/{id}/cancel`. `GET /conversations/{id}` renvoie, pour chaque réponse, ses `actions` avec l'état actuel des cartes (`pending`, `confirmed`, `cancelled`, `expired`).

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
- Cartes : `asst_messages.actions` (migration `assistant_0003`) ; l'issue de chaque carte est lue dans `core_tool_confirmations`. Supprimer une conversation annule ses cartes en attente et efface leurs arguments.
- Réponses en `Cache-Control: no-store`.

## Exploitation

Métrique `lorakus_assistant_replies_total{status, reason}` ; alertes et procédures dans [le runbook du moteur IA](../runbooks/ai.md).
