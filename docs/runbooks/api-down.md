# API injoignable ou dégradée

Alertes : `LorakusApiDown` (critique), `LorakusHighErrorRate`, `LorakusHighLatency`, `LorakusApiHighMemory` (avertissements).

Préparer la session : [README](README.md#session).

## Symptôme

- `LorakusApiDown` : Prometheus ne collecte plus les métriques de l'API depuis 2 minutes. Mesuré le 2026-11-10 : alerte Discord 2 min 21 s après l'arrêt de l'API.
- Les trois avertissements : l'API répond, mais mal (erreurs 5xx, lenteur, mémoire au-dessus de 650 Mo pour une limite de 768 Mo ; environ 545 Mo au repos est normal avec le modèle d'embeddings chargé, mesuré le 2026-11-13).

## Vérifications

```bash
dc ps && curl -fsS -m 5 http://127.0.0.1:8001/api/health/ready ; echo ; dc logs --tail 50 api
```

```bash
docker inspect -f '{{.State.Status}} redémarrages={{.RestartCount}} OOM={{.State.OOMKilled}} code={{.State.ExitCode}}' lorakus-api-1 && free -m && df -h /
```

- `/api/health/ready` vérifie aussi la base : s'il échoue alors que `/api/health` répond, le problème est PostgreSQL.
- Un déploiement vient-il d'avoir lieu ? `/opt/lorakus/app/infra/deploy/deploy.sh status` (champ `LORAKUS_RELEASED_AT`).

## Causes probables

| Constat | Cause |
| --- | --- |
| Conteneur `api` arrêté ou en boucle de redémarrage, juste après un déploiement | Version défectueuse (le test de santé du déploiement aurait dû la refuser : à signaler dans la note d'incident) |
| `OOM=true` ou mémoire de l'API proche de 768 Mo | Fuite ou charge mémoire ; le conteneur est tué par sa limite |
| Journal `modele d'embeddings absent` ou `modele illisible` au démarrage | Image sans le modèle ou fichier abîmé : l'API refuse de démarrer en production plutôt que de chercher avec de faux vecteurs. Retour à la version précédente, puis vérifier le test de fumée de l'image dans le workflow Publish |
| `postgres` non `healthy`, erreurs de connexion dans les journaux de l'API | Base arrêtée, disque plein ([disk-full](disk-full.md)) ou mémoire du serveur épuisée ([host](host.md)) |
| Tous les conteneurs arrêtés | Serveur redémarré et Docker non relancé, ou arrêt manuel |
| L'API répond en local mais l'alerte persiste | Prometheus ne joint plus `api:9464` (réseau Docker) : `dc restart prometheus` |

## Actions

1. **API arrêtée ou bloquée, sans déploiement récent** : `dc up -d --wait api`, puis revérifier. Si elle retombe, lire `dc logs --tail 200 api` avant toute autre action.
2. **Problème apparu après un déploiement** : retour à la version précédente depuis le Dell, `gh workflow run deploy.yml -f action=rollback` (10 secondes mesurées), puis corriger par une PR.
3. **PostgreSQL arrêté** : `dc up -d --wait postgres`, lire `dc logs --tail 100 postgres`. S'il refuse de démarrer faute de place : [disk-full](disk-full.md). Si les données sont corrompues : [restore](restore.md).
4. **Tout est arrêté** : `sudo systemctl status docker`, puis `dc up -d --wait`.
5. **Mémoire élevée sans fuite évidente** : mesurer le modèle d'embeddings seul dans le conteneur, `dc run --rm -T --no-deps api python -m lorakus.ai.providers.check </dev/null` (conteneur jetable : jamais `dc exec` dans `api`, une seconde copie du modèle sous la même limite pourrait le faire tuer ; DEPLOYMENT.md).
5. **Dégradation sans panne** (erreurs, lenteur, mémoire) : chercher la route en cause dans Grafana (tableau « Lorakus API »), relever l'identifiant de requête (`request_id`) d'une erreur dans `dc logs api`. `dc restart api` ne se justifie que pour la mémoire, et après avoir noté les chiffres.

## Retour arrière

- Un `dc up` ou `dc restart` ne change pas la version : rien à annuler.
- Après un retour à la version précédente : `release.env` et `release.previous.env` sont échangés. Un nouveau `rollback` ramène donc la version défectueuse : ne pas le lancer deux fois. Redéployer la version corrigée avec `gh workflow run deploy.yml`.

## Fin d'incident

L'alerte passe à « Résolu » dans Discord. Vérifier qu'aucune erreur 5xx n'apparaît pendant 10 minutes.
