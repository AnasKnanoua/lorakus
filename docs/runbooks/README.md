# Runbooks

Un runbook répond à une seule question : **« l'alerte vient de tomber, je fais quoi ? »**. Chaque règle d'alerte porte une annotation `runbook_url` vers l'un de ces fichiers ; le lien apparaît dans le message Discord. `make obs-check` (donc la CI) refuse une règle sans runbook ou un lien vers un fichier absent.

| Runbook | Alertes concernées |
| --- | --- |
| [API injoignable ou dégradée](api-down.md) | `LorakusApiDown`, `LorakusHighErrorRate`, `LorakusHighLatency`, `LorakusApiHighMemory` |
| [Sauvegarde en échec ou manquante](backup-failed.md) | `LorakusBackupFailed`, `LorakusBackupMissing`, `LorakusBackupNeverRecorded` |
| [Disque plein](disk-full.md) | `LorakusDiskSpaceLow`, `LorakusDiskSpaceCritical` |
| [Mémoire basse, métriques du serveur absentes](host.md) | `LorakusHostMemoryLow`, `LorakusNodeExporterDown` |
| [Production disparue](production-down.md) | Message healthchecks.io « DOWN », `LorakusHeartbeatFailing` |
| [Worker : jobs et événements](worker.md) | `LorakusWorkerDown`, `LorakusWorkerStalled`, `LorakusWorkerHighMemory`, `LorakusOutboxBacklog`, `LorakusOutboxDeadEvents` |
| [Moteur IA et assistant](ai.md) | `LorakusAiProviderFailing`, `LorakusAiUsageNotRecorded`, `LorakusAiSpendHigh`, `LorakusAiBudgetReached`, `LorakusAssistantInternalError` |
| [Déploiement en échec](deploy-failed.md) | Aucune : le workflow `Deploy` est rouge |
| [Restaurer une sauvegarde](restore.md) | Aucune : procédure appelée par les autres runbooks |
| [Pièges déjà rencontrés](pitfalls.md) | — |

Tous suivent le même plan : symptôme, vérifications, causes probables, actions, retour arrière.

## Session

```bash
ssh lorakus-prod
```

Puis, sur le serveur, avec l'utilisateur `deploy` (`sudo -iu deploy` si la session s'ouvre sous un autre compte) :

```bash
cd /opt/lorakus/app && dc() { docker compose -f compose.yml -f compose.observability.yml -f compose.prod.yml --env-file /opt/lorakus/.env --env-file /opt/lorakus/release.env "$@"; } && dc ps
```

`dc` est la commande `docker compose` de la production, avec tous ses fichiers. Elle n'existe que dans la session en cours. Les runbooks l'utilisent partout.

## Règles valables pour tous les runbooks

- **Observer avant d'agir** : `dc ps`, `dc logs --tail 100 <service>`, `df -h /`, `free -m`. Noter l'heure et ce qui est constaté.
- **Jamais** `docker volume prune`, `docker system prune --volumes` ni `dc down -v` : les volumes contiennent la base de données.
- **Jamais** de modification à la main dans `/opt/lorakus/app` : ce dossier est remis sur un commit de `main` à chaque déploiement. Une correction passe par une PR puis `gh workflow run deploy.yml`.
- `docker compose run` et `docker compose exec` lancés depuis un script ou une boucle : toujours `-T </dev/null` (voir [pièges](pitfalls.md)).
- Ne jamais toucher à `oraclevps` (Anime Notif) : il est hors du périmètre de Lorakus.
- Après un incident réel : une note dans `docs/incidents/AAAA-MM-JJ-titre.md` sous 7 jours (`SECURITY.md`), et le runbook corrigé s'il était faux ou incomplet.

## Commandes utiles

| Besoin | Commande |
| --- | --- |
| Version en service et précédente | `/opt/lorakus/app/infra/deploy/deploy.sh status` |
| Santé de l'API | `curl -fsS http://127.0.0.1:8001/api/health/ready` |
| Alerte de test vers Discord | `/opt/lorakus/app/infra/deploy/deploy.sh alert-test` |
| Sauvegarde immédiate | `/opt/lorakus/app/infra/deploy/deploy.sh backup` |
| Retour à la version précédente (depuis le Dell) | `gh workflow run deploy.yml -f action=rollback` |
| Grafana depuis le Dell | `ssh -L 3000:localhost:3000 lorakus-prod` puis http://localhost:3000 |
| Alertes en cours depuis le Dell | `ssh -L 9093:localhost:9093 lorakus-prod` puis http://localhost:9093 |
