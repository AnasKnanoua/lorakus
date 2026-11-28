# Rappels et notifications : signaux, Web Push, Telegram

Alertes (avertissements, composant `worker` : `LorakusWorkerDown` les masque) : `LorakusSignalsDispatchLate`, `LorakusSignalsDispatchErrors`, `LorakusInterventionDuplicate`, `LorakusNotificationsFailing`, `LorakusTelegramPollStopped`.

Préparer la session : [README](README.md#session). Fonctionnement : ADR 0042 et ses amendements.

## Symptôme

| Alerte | Signification |
| --- | --- |
| `LorakusSignalsDispatchLate` | `signals.dispatch` ne s'est pas terminé depuis 5 minutes alors que le worker répond : aucune carte « À noter » nouvelle, aucune notification |
| `LorakusSignalsDispatchErrors` | Le traitement d'un signal a planté ; les autres continuent, celui-ci replante à chaque reprise tant que la cause reste |
| `LorakusInterventionDuplicate` | La base a refusé une seconde intervention pour la même cause : rien n'est parti deux fois, mais deux traitements se sont chevauchés (critère de fin de la P5 : à 0) |
| `LorakusNotificationsFailing` | Au moins deux envois (Web Push ou Telegram) en échec en 6 heures ; un envoi en échec n'est jamais repris, la carte reste dans Ma journée |
| `LorakusTelegramPollStopped` | Un jeton est configuré mais le bot n'a pas relevé ses messages depuis 10 minutes ; les idées envoyées attendent chez Telegram (24 heures au plus) |

Un appareil désabonné (réponse 404 ou 410 du service de notification) n'est pas une panne : il est oublié, sans alerte.

## Vérifications

Journaux du worker sur ces sujets :

```bash
dc logs --since 2h worker 2>&1 | grep -E 'signal_dispatch_crashed|intervention_duplicate|push_|telegram_' | tail -40
```

Signaux en cours et dernières interventions (aucun texte de rappel, seulement les états) :

```bash
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select name, status, outcome, next_check_at, locked_until from lorakus.core_signals where status = 'active' order by next_check_at limit 20" -c "select level, channel, reason, delivered, failed, created_at from lorakus.core_interventions order by created_at desc limit 20" </dev/null
```

Appareils en échec (jamais l'adresse d'abonnement) :

```bash
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select label, failures, last_success_at, last_failure_at from lorakus.core_push_subscriptions order by last_failure_at desc nulls last" </dev/null
```

Job de relève et d'envoi dans Procrastinate :

```bash
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select task_name, status, count(*), max(scheduled_at) from lorakus.procrastinate_jobs where task_name in ('signals.dispatch', 'telegram.poll') group by 1, 2 order by 1, 2" </dev/null
```

État du bot vu par Telegram (le jeton reste dans le conteneur ; seuls l'existence d'un webhook, le nombre de messages en attente et la dernière erreur s'affichent) :

```bash
dc exec -T worker python -c 'import json, os, urllib.request; t = os.environ["LORAKUS_TELEGRAM_BOT_TOKEN"]; r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{t}/getWebhookInfo", timeout=10))["result"]; print("webhook:", bool(r.get("url")), "| en attente:", r.get("pending_update_count"), "| erreur:", r.get("last_error_message"))'
```

## Causes probables

| Constat | Cause |
| --- | --- |
| `signals.dispatch` absent ou en `failed` dans Procrastinate | Le job plante avant la fin (base injoignable : [api-down](api-down.md)) ou n'est plus enregistré (régression : [deploy-failed](deploy-failed.md)) |
| `signal_dispatch_crashed` répété pour le même signal | Bogue sur un cas précis (module retiré, sujet supprimé entre deux passages, donnée inattendue) |
| Doublon refusé juste après un déploiement | Deux workers en même temps pendant la bascule ; un seul cas isolé est sans conséquence |
| Doublon refusé hors déploiement | Bail trop court pour un envoi lent (`LEASE`, 2 minutes) ou bogue de réservation : à corriger |
| `push_refused` ou `push_transport_failed` sur un appareil, les autres passent | Service de notification de cet appareil indisponible, ou abonnement abîmé : le retirer et le réactiver depuis la page Notifications |
| Tous les envois en échec | Sortie réseau du serveur coupée, clés VAPID changées (tous les abonnements sont alors refusés) |
| `telegram_notify_failed` ou `telegram_reply_failed` | Bot bloqué par l'utilisateur, discussion supprimée, ou Telegram indisponible |
| `telegram_poll_failed reason=conflict` (409), ou `webhook: True` | Un autre programme relève les messages du même bot, ou un webhook est actif |
| `telegram_poll_failed reason=unauthorized` (401) | Jeton révoqué dans BotFather |
| `telegram_poll_failed reason=unreadable` ou `rejected` | Réponse inattendue de Telegram (changement d'API) |

## Actions

1. **Dispatch en retard** : lire l'erreur du dernier job `signals.dispatch` dans les journaux. Base injoignable : [api-down](api-down.md). Worker bloqué : [worker](worker.md). Rien d'évident : `dc restart worker`, puis vérifier qu'un passage a lieu dans la minute (l'alerte retombe). Aucun rappel n'est perdu : les signaux en attente sont repris au passage suivant.
2. **Traitement en erreur** : relever l'identifiant du signal (`signal=` dans `signal_dispatch_crashed`) et la trace, ouvrir une PR de correction avec un test qui reproduit le cas. En attendant, le signal fautif peut être retiré sans rien envoyer (remplacer `<id>`, noter l'heure et la raison) :

   ```bash
   dc exec -T postgres psql -U lorakus_admin -d lorakus -c "update lorakus.core_signals set status = 'withdrawn', outcome = 'ops', next_check_at = null, locked_until = null where id = '<id>' and status = 'active'" </dev/null
   ```

   `UPDATE 1` attendu. Un signal retiré n'a plus d'échéance (`next_check_at`) : la contrainte `status` de la table refuse un retrait qui la garde (l'ancienne version de cette commande échouait ainsi, trouvé par `test_runbook_sql.py`).
3. **Doublon refusé** : vérifier l'heure (déploiement en cours ou non). Hors déploiement, ouvrir une PR ; ne rien changer à la contrainte d'unicité, c'est elle qui a empêché le second envoi.
4. **Envois en échec** : un seul appareil touché → le retirer depuis la page Notifications et le réactiver. Tous touchés → vérifier la sortie réseau (`dc exec -T worker python -c 'import urllib.request; print(urllib.request.urlopen("https://fcm.googleapis.com", timeout=10).status)'`, une réponse HTTP même en erreur suffit) et que `LORAKUS_VAPID_PRIVATE_KEY` n'a pas changé (`push_without_vapid_keys` dans les journaux : clé absente) dans `/opt/lorakus/.env`. Telegram seul touché → envoyer un message au bot pour vérifier qu'il n'est pas bloqué.
5. **Relève Telegram arrêtée** :
   - 409 ou webhook actif : arrêter l'autre programme qui relève ce bot. Pour supprimer un webhook (les messages en attente sont gardés) : la commande de vérification ci-dessus, avec `deleteWebhook` à la place de `getWebhookInfo`.
   - 401 : nouveau jeton dans BotFather, puis `DEPLOYMENT.md` (§10, « Jeton du bot Telegram »).
   - Autre : `dc restart worker`. Les messages non relevés restent 24 heures chez Telegram et sont traités à la reprise ; un message relu après un redémarrage donne au pire « Cette idée est déjà dans ta boîte ».

## Retour arrière

Après une version défectueuse : [deploy-failed](deploy-failed.md). Les migrations des signaux et de Telegram ont une descente, mais un retour arrière garde les rappels déjà envoyés (jamais renvoyés).
