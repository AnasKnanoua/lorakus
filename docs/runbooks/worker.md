# Worker : jobs et événements

Alertes : `LorakusWorkerDown`, `LorakusWorkerStalled` (critiques), `LorakusWorkerHighMemory`, `LorakusOutboxBacklog`, `LorakusOutboxDeadEvents` (avertissements).

Préparer la session : [README](README.md#session).

## Symptôme

| Alerte | Signification |
| --- | --- |
| `LorakusWorkerDown` | Le worker ne répond plus : jobs et événements ne sont plus traités (l'API continue de fonctionner) |
| `LorakusWorkerStalled` | Le processus vit, mais sa boucle ne tourne plus depuis 2 minutes |
| `LorakusWorkerHighMemory` | Plus de 200 Mo pour une limite de 256 Mo |
| `LorakusOutboxBacklog` | Un événement attend depuis plus de 5 minutes |
| `LorakusOutboxDeadEvents` | Un événement a échoué 8 fois et n'est plus retenté |

## Vérifications

```bash
dc ps worker && dc logs --tail 80 worker
```

```bash
docker inspect -f '{{.State.Status}} redémarrages={{.RestartCount}} OOM={{.State.OOMKilled}}' lorakus-worker-1 && docker stats --no-stream lorakus-worker-1
```

Événements en attente ou abandonnés :

```bash
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select id, event_type, attempts, next_attempt_at, dead_at, left(last_error, 120) from lorakus.core_outbox where published_at is null order by id limit 20" </dev/null
```

Jobs en échec :

```bash
dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select id, task_name, status, attempts, scheduled_at from lorakus.procrastinate_jobs where status in ('failed', 'todo') order by id desc limit 20" </dev/null
```

## Causes probables

| Constat | Cause |
| --- | --- |
| Conteneur arrêté ou en boucle de redémarrage après un déploiement | Version défectueuse : [deploy-failed](deploy-failed.md) |
| `OOM=true` | Un job charge trop de données en mémoire |
| Boucle bloquée, `event_handler_failed` absent des journaux | Un handler ou un job attend indéfiniment (appel externe sans délai d'expiration) |
| `last_error` identique sur plusieurs événements | Un handler en panne (bogue, service externe indisponible) |
| PostgreSQL injoignable dans les journaux | [api-down](api-down.md) |

## Actions

1. **Worker arrêté ou bloqué** : `dc restart worker`, puis vérifier `dc logs --tail 30 worker` (ligne `worker_started`). Les jobs en cours sont repris : un job commencé mais non terminé est relancé (handlers idempotents).
2. **Handler en panne** : corriger par une PR. Les événements en attente sont retentés seuls (attente croissante, jusqu'à 1 heure).
3. **Événements abandonnés, une fois la cause corrigée** : les remettre en file. Les handlers déjà réussis ne sont pas rejoués.

   ```bash
   dc exec -T postgres psql -U lorakus_admin -d lorakus -c "update lorakus.core_outbox set dead_at = null, attempts = 0, next_attempt_at = now() where dead_at is not null" </dev/null
   ```

4. **Mémoire** : noter le job en cours dans les journaux, `dc restart worker`, puis corriger le job (traitement par lots).

## Retour arrière

Un redémarrage ne change pas la version. Les événements remis en file ne sont livrés qu'aux handlers qui ne les ont pas encore traités.
