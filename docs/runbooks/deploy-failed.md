# Déploiement en échec

Aucune alerte : le workflow `Deploy` est rouge, ou `deploy.sh` affiche `ECHEC`.

Préparer la session : [README](README.md#session).

## Symptôme

`gh workflow run deploy.yml` se termine en erreur. Repères mesurés le 2026-11-10 : déploiement complet en 26 secondes, retour arrière en 10 secondes.

## Vérifications

Depuis le Dell :

```bash
gh run list --workflow deploy.yml --limit 3 && gh run view --log-failed "$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')" | tail -40
```

Puis l'état réel du serveur, qui seul fait foi :

```bash
gh workflow run deploy.yml -f action=status
```

ou, sur le serveur : `/opt/lorakus/app/infra/deploy/deploy.sh status && dc ps && curl -fsS http://127.0.0.1:8001/api/health/ready`.

## Causes probables

Le message d'erreur dit à quelle étape le déploiement s'est arrêté, et donc ce qui a été modifié.

| Message | Cause | État de la production |
| --- | --- | --- |
| `Image introuvable pour le commit …` ou `not found` dans le job `staging` | Le workflow `Publish` a échoué ou n'était pas terminé. `make deploy` l'attend désormais (`infra/deploy/wait-publish.sh`) ; le cas ne se produit plus qu'avec `gh workflow run` lancé à la main | Inchangé |
| `denied` dans `Publish`, à la première publication d'une nouvelle image | Les jobs amd64 et arm64 créent le paquet GHCR en même temps ([pièges](pitfalls.md)) | Inchangé |
| `Host key verification failed` | L'empreinte SSH du serveur a changé, ou la variable `DEPLOY_KNOWN_HOSTS` est fausse | Inchangé |
| `Permission denied (publickey)` | Secret `DEPLOY_SSH_KEY` ou ligne `authorized_keys` de `deploy` modifiés | Inchangé |
| `un autre deploiement est deja en cours` | Verrou tenu par un déploiement ou une sauvegarde | Inchangé |
| `le commit … n'appartient pas a la branche main` | Déploiement lancé hors de `main` | Inchangé |
| `telechargement des images impossible` | GHCR injoignable, ou paquet redevenu privé | Inchangé |
| `sauvegarde impossible : deploiement annule` | Sauvegarde avant migration en échec : [backup-failed](backup-failed.md) | Inchangé |
| `la version precedente est de nouveau en service` | Migration, démarrage ou test de santé en échec ; retour automatique réussi | Version d'avant, mais une migration a pu être appliquée |
| `le retour automatique a aussi echoue` | La version d'avant ne redémarre pas non plus | **En panne** |
| `STAGING EN ECHEC : …` (job `staging`) | La nouvelle version échoue sur le staging éphémère : le message dit quelle étape | Inchangé |
| Le workflow reste en attente | Approbation de l'environnement `production` non donnée | Inchangé |

## Actions

1. **Production inchangée** : corriger la cause, relancer `gh workflow run deploy.yml -f action=deploy`.
   - `Publish` en échec : `gh run list --workflow publish.yml --limit 3`, puis `gh run rerun <id> --failed`.
   - Empreinte SSH : ne **jamais** la mettre à jour sans l'avoir comparée sur le serveur (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`). Une empreinte qui change sans réinstallation du serveur est un incident de sécurité (`SECURITY.md`).
   - Staging en échec : lire le job `staging` (`gh run view --log-failed`). Il affiche l'état des services et la fin des journaux. Corriger par une PR. En cas d'urgence absolue seulement (correctif de sécurité, staging cassé par GitHub), `make deploy-skip-staging` : décision à consigner.
2. **Retour automatique réussi** : la production tourne sur l'ancienne version. Lire `dc logs --tail 100 api` et `dc logs --tail 100 migrate` pour comprendre, corriger par une PR. Si une migration a été appliquée, le schéma reste compatible avec l'ancienne version (expand/contract, ADR 0011) : ne pas l'annuler à la main.
3. **Retour automatique en échec** : traiter comme une panne, [api-down](api-down.md). La version attendue est dans `/opt/lorakus/release.env` ; `dc up -d --wait` la relance. Si la base est en cause : [restore](restore.md).
4. **Sauvegarde avant migration impossible, déploiement urgent** (correctif de sécurité, B2 en panne) : décision consciente, à consigner. Sur le serveur, `LORAKUS_DEPLOY_SKIP_BACKUP=1` permet de s'en passer ; le workflow GitHub ne transmet pas cette variable, volontairement.

## Retour arrière

`gh workflow run deploy.yml -f action=rollback` remet la version précédente (configuration et images), sans rejouer de migration. À n'utiliser qu'après un déploiement **réussi** qui se révèle défectueux : après un échec, la production est déjà sur l'ancienne version.

## Après l'incident

Checklist de `DEPLOYMENT.md` §10.
