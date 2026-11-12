# Moteur IA et assistant

Le chat passe par le `ModelRouter` (`backend/lorakus/ai/router.py`). Quand l'IA ne peut pas répondre, l'assistant envoie un **message de secours** fixe : l'utilisateur n'est jamais laissé sans réponse et son message est toujours enregistré. Ces alertes ne sont donc jamais critiques ; elles disent que les réponses se dégradent ou que l'argent part plus vite que prévu.

Session et raccourci `dc` : voir [README](README.md#session).

## Commandes utiles

```bash
# Derniers appels IA et refus, sans aucun contenu de conversation.
dc logs --since 1h api </dev/null | grep -E '"event": "ai_(call|refused|provider_failed|usage_record_failed)"' | tail -n 30

# Dépense du mois par jour, tous utilisateurs confondus.
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select date_trunc('day', created_at) as jour, count(*) as appels, sum(cost_usd) as dollars from lorakus.core_ai_usage where created_at >= date_trunc('month', now()) group by 1 order by 1" </dev/null
```

## Couper toute l'IA (incident)

Fuite suspectée de la clé, dépense qui s'emballe, comportement inquiétant du modèle :

```bash
sed -i 's/^LORAKUS_AI_KILL_SWITCH=.*//' /opt/lorakus/.env && echo 'LORAKUS_AI_KILL_SWITCH=true' >> /opt/lorakus/.env && dc up -d --force-recreate api
```

L'API redémarre en quelques secondes ; tout message reçoit le message de secours, rien ne part chez le fournisseur. Pour rétablir : remplacer `true` par `false`, puis la même commande `dc up`. Si la clé a fuité : la révoquer dans la console Anthropic, en créer une nouvelle, la remplacer dans `/opt/lorakus/.env` (ligne `LORAKUS_ANTHROPIC_API_KEY`), puis `dc up -d --force-recreate api`.

## LorakusAiProviderFailing

- **Symptôme** : au moins 3 appels en échec et aucun réussi en 15 minutes ; le chat répond par le message de secours.
- **Vérifier** : la page d'état d'Anthropic ; les journaux `ai_provider_failed`, dont le champ `kind` donne la cause.
- **Selon `kind`** :
  - `unavailable` ou `rate_limited` : panne ou surcharge chez le fournisseur. Rien à faire ; le disjoncteur réessaie seul toutes les 2 minutes, et l'alerte se résout au premier appel réussi.
  - `misconfigured` : clé refusée (révoquée, crédit épuisé). Vérifier le crédit dans la console Anthropic, puis remplacer la clé (section précédente).
  - `rejected` : requête refusée (modèle retiré, format). Vérifier que le modèle de `routing.toml` existe toujours ; corriger par une PR.

## LorakusAiUsageNotRecorded

- **Symptôme** : un appel réussi n'a pas pu être écrit dans `core_ai_usage` ; le plafond mensuel le sous-estime.
- **Vérifier** : journaux `ai_usage_record_failed` (type d'erreur) ; santé de PostgreSQL (`dc ps`, [runbook de l'API](api-down.md)).
- **Action** : corriger la cause côté base. Les appels non enregistrés restent visibles dans la métrique `lorakus_ai_cost_usd_total` et dans la console Anthropic. Le crédit prépayé sans rechargement reste la limite absolue.

## LorakusAiSpendHigh

- **Symptôme** : plus de 0,50 $ en 24 heures, environ dix fois l'usage attendu.
- **Vérifier** : la requête « Dépense du mois par jour » ci-dessus ; le nombre d'appels par heure dans les journaux `ai_call`.
- **Causes probables** : une boucle (même requête répétée), un script ou un client qui renvoie des messages, ou un usage réellement intense.
- **Action** : en cas de doute, couper l'IA (section ci-dessus), puis chercher la cause. Le plafond par utilisateur (3 $ par mois) arrête de toute façon les appels quand il est atteint.

## LorakusAiBudgetReached

- **Symptôme** : un utilisateur a atteint son plafond mensuel ; ses messages reçoivent le message de secours jusqu'au 1er du mois (UTC).
- **Action** : rien d'urgent. Si c'est inattendu, voir `LorakusAiSpendHigh`. Pour relever le plafond (décision D-D à réviser), modifier `LORAKUS_AI_MONTHLY_BUDGET_USD` dans `/opt/lorakus/.env`, puis `dc up -d --force-recreate api`.

## LorakusAssistantInternalError

- **Symptôme** : une réponse s'est terminée par le message d'erreur interne : c'est un bogue, pas une panne du fournisseur.
- **Vérifier** : `dc logs --since 1h api </dev/null | grep -A 30 assistant_reply_failed` (trace de l'exception).
- **Action** : ouvrir une issue avec la trace (sans contenu de conversation), corriger par une PR. Si l'erreur se répète à chaque message, `make rollback` depuis le Dell.
