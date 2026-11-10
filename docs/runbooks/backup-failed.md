# Sauvegarde en échec ou manquante

Alertes : `LorakusBackupFailed` (avertissement), `LorakusBackupMissing` et `LorakusBackupNeverRecorded` (critiques).

Préparer la session : [README](README.md#session).

## Symptôme

| Alerte | Signification |
| --- | --- |
| `LorakusBackupFailed` | La dernière tentative s'est terminée en erreur |
| `LorakusBackupMissing` | Aucune réussite depuis plus de 26 heures : les données de la journée ne sont pas protégées |
| `LorakusBackupNeverRecorded` | Aucune tentative enregistrée depuis 26 heures : le minuteur ne tourne pas, ou ses métriques ne sont plus lues |

La sauvegarde part chaque nuit vers 03:30 UTC (décalage aléatoire de 20 minutes au plus), et avant chaque migration.

## Vérifications

```bash
systemctl list-timers lorakus-backup.timer --no-pager && systemctl status lorakus-backup.service --no-pager | head -15 && journalctl -u lorakus-backup.service -n 60 --no-pager
```

```bash
dc run --rm --no-deps -T backup latest </dev/null && dc exec -T node-exporter cat /textfile/lorakus_backup.prom </dev/null | grep -v '^#'
```

La première commande donne le nom de la dernière sauvegarde présente sur B2 (son horodatage est dans le nom) ; la seconde, ce que le serveur croit avoir fait.

## Causes probables

| Message dans le journal | Cause |
| --- | --- |
| `verrou toujours pris apres 1800 s` | Un déploiement est resté bloqué plus de 30 minutes |
| `401`, `unauthorized`, `bad_auth_token` (rclone) | Clé B2 révoquée, expirée ou mal saisie |
| `cap exceeded`, `storage cap`, `403` | Plafond du compte B2 atteint |
| `dial tcp`, `no such host`, `timeout` | Réseau du serveur ou panne de Backblaze |
| `pg_dump: error` | PostgreSQL arrêté ou mot de passe du rôle `lorakus_migrator` incohérent |
| `No space left on device` | `/tmp` du conteneur (512 Mo) trop petit pour le dump : la base a grossi |
| Aucune ligne récente dans le journal | Minuteur désactivé ou non réinstallé (`DEPLOYMENT.md` §7.1) |
| Le journal dit « Sauvegarde envoyee » mais l'alerte persiste | `node-exporter` arrêté ou métriques non lues : [host](host.md) |

## Actions

1. Corriger la cause, puis **relancer une sauvegarde** et lire le résultat :

   ```bash
   /opt/lorakus/app/infra/deploy/deploy.sh backup
   ```

2. Minuteur absent ou désactivé : le réinstaller (`DEPLOYMENT.md` §7.1).
3. Verrou bloqué : vérifier qu'aucun déploiement ne tourne (`pgrep -af deploy.sh`), puis relancer. Le verrou (`flock`) se libère seul à la fin du processus qui le tient ; ne pas supprimer `deploy.lock`.
4. `/tmp` trop petit : augmenter `tmpfs` du service `backup` dans `compose.yml` par une PR.
5. Clé B2 à remplacer : section suivante.

Les alertes se résolvent seules au passage suivant de Prometheus (une minute environ).

### Remplacer la clé B2 du serveur

Chaque machine a sa propre clé (`DEPLOYMENT.md` §7.2). Créer la nouvelle clé comme indiqué là-bas, puis sur le serveur :

```bash
sed -i -e '/^B2_KEY_ID=/d' -e '/^B2_APP_KEY=/d' /opt/lorakus/.env && /opt/lorakus/app/infra/deploy/init-env.sh && /opt/lorakus/app/infra/deploy/deploy.sh backup
```

`init-env.sh` ne redemande que les deux valeurs supprimées. Une fois la sauvegarde réussie, supprimer l'ancienne clé dans Backblaze.

## Retour arrière

Une sauvegarde n'écrit que de nouveaux fichiers sur B2 : rien à annuler. Si la nouvelle clé B2 ne fonctionne pas et que l'ancienne existe encore, la remettre par la même commande.

## Vérifier qu'une sauvegarde est réellement utilisable

Depuis le Dell (partage de connexion du téléphone à METU, voir [pièges](pitfalls.md)) : `make restore-test`.
