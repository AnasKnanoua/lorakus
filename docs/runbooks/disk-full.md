# Disque plein

Alertes : `LorakusDiskSpaceLow` (moins de 15 % libres, avertissement), `LorakusDiskSpaceCritical` (moins de 5 %, critique).

Préparer la session : [README](README.md#session).

## Symptôme

Le disque principal se remplit. À moins de 5 %, PostgreSQL risque de s'arrêter pour protéger ses données, et les sauvegardes d'échouer.

## Vérifications

```bash
df -h / && docker system df && sudo du -xh --max-depth=1 /var/lib/docker 2>/dev/null | sort -h | tail -6
```

```bash
docker system df -v | sed -n '/VOLUME NAME/,$p' && sudo journalctl --disk-usage
```

## Causes probables

| Constat | Cause |
| --- | --- |
| Beaucoup d'images « reclaimable » | Images d'avant le nettoyage automatique (2026-11-20), ou d'un autre projet. Depuis cette date, chaque déploiement réussi supprime les images Lorakus qui ne sont ni la version en service ni la précédente (`prune_images` dans `deploy.sh`) |
| Volume `lorakus_postgres-data` en forte hausse | Croissance des données, ou table qui enfle |
| Volume `lorakus_prometheus-data` au-dessus de 1 Go | Anormal : la rétention est bornée à 15 jours et 1 Go |
| `/var/log` ou journal systemd volumineux | Journaux du système (ceux des conteneurs sont bornés à 30 Mo chacun) |
| Fichiers `*.dump` dans un dossier personnel | Restauration passée dont le fichier n'a pas été supprimé |

## Actions

Dans l'ordre, en s'arrêtant dès que l'espace libre repasse au-dessus de 20 % :

1. **Images inutilisées** (sans risque : seules les images qu'aucun conteneur n'utilise sont supprimées ; aucun volume n'est touché). La version précédente part aussi : un retour arrière la retéléchargera.

   ```bash
   docker image prune -a -f && docker builder prune -f && df -h /
   ```

2. **Journal systemd** : `sudo journalctl --vacuum-size=200M`.
3. **Fichiers de restauration oubliés** : `ls -lh ~/*.dump /tmp/*.dump 2>/dev/null`, puis `shred -u <fichier>`.
4. **PostgreSQL** : mesurer avant de décider.

   ```bash
   dc exec -T postgres psql -U lorakus_admin -d lorakus -c "select relname, pg_size_pretty(pg_total_relation_size(c.oid)) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'lorakus' and c.relkind = 'r' order by pg_total_relation_size(c.oid) desc limit 10" </dev/null
   ```

   Une table anormalement grosse se traite par une PR (rétention, purge), jamais par une suppression à la main.
5. Si rien ne suffit : agrandir le volume de démarrage dans la console Oracle (dans la limite du quota Always Free, partagé avec `oraclevps` : vérifier avant), puis `sudo /usr/libexec/oci-growfs -y`.

**À ne jamais faire** : `docker volume prune`, `docker system prune --volumes`, supprimer des fichiers dans `/var/lib/docker/volumes`.

## Retour arrière

- Les images supprimées sont retéléchargées au prochain déploiement ou retour arrière (qui demande alors le réseau vers GHCR).
- Un agrandissement de volume ne se réduit pas.

## Après l'incident

L'accumulation d'images est traitée depuis le 2026-11-20 (alertes « avertissement » puis « critique » reçues ce jour-là, après une série de déploiements). Si le disque se remplit encore, la cause est ailleurs : reprendre les vérifications ci-dessus. Rappel : ces alertes mesurent le disque `/` du serveur, pas celui d'un poste de travail.
