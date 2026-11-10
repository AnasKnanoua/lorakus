# Pièges déjà rencontrés

Problèmes réellement rencontrés sur Lorakus, avec leur correction. À compléter après chaque incident : un piège noté ici ne coûte plus qu'une minute la fois suivante.

## Le nom d'hôte revient à sa valeur d'origine (Oracle Linux)

- **Symptôme** : après un redémarrage ou un simple événement réseau, `hostnamectl` affiche de nouveau le nom saisi à la création de l'instance.
- **Cause** : sur les images Oracle, le script `oci-dhclient.sh` réapplique ce nom, par-dessus cloud-init et NetworkManager.
- **Correction** : `PRESERVE_HOSTINFO=2` dans `/etc/oci-hostname.conf`, en plus des réglages cloud-init et NetworkManager. Avec la valeur `2`, Oracle ne met plus `/etc/hosts` à jour : y corriger l'alias à la main. Détail et vérification : `DEPLOYMENT.md` §2.1.
- **Portée** : images Oracle uniquement. Sans objet sur la VM Azure.

## `denied` à la première publication d'une image sur GHCR

- **Symptôme** : le workflow `Publish` échoue avec `denied` sur l'un des deux jobs (amd64 ou arm64), uniquement la première fois qu'une **nouvelle** image est publiée.
- **Cause** : les deux jobs créent le paquet GHCR au même instant ; l'un des deux est refusé.
- **Correction** : `gh run rerun <id> --failed`. Le paquet existe alors, le second passage réussit. Penser ensuite à rendre le nouveau paquet public (réglage irréversible), sinon le serveur ne peut pas le télécharger.

## `docker compose run` avale l'entrée standard

- **Symptôme** : un script s'arrête sans erreur après un `docker compose run`, ou une boucle `while read` ne traite que sa première ligne ; une commande passée par SSH se termine trop tôt.
- **Cause** : `docker compose run` (et `exec`) se branche par défaut sur l'entrée standard et la lit jusqu'au bout, y compris la suite du script ou les données destinées à la commande suivante.
- **Correction** : toujours `docker compose run --rm -T <service> </dev/null` dans un script (`-T` : pas de terminal ; `</dev/null` : rien à lire). C'est le cas partout dans `deploy.sh`. Seule exception voulue : la restauration, qui envoie le fichier de sauvegarde sur l'entrée standard.

## Backblaze B2 inaccessible depuis le réseau de METU

- **Symptôme** : `make backup` et `make restore-test` échouent sur le Dell, depuis le campus seulement.
- **Cause** : le DNS du campus redirige les domaines de téléchargement de Backblaze.
- **Correction** : partage de connexion du téléphone, Wi-Fi du téléphone désactivé. Sans effet sur la production.

## Une alerte de test sans `[production]` dans le titre

- **Symptôme** : une alerte envoyée avec `amtool alert add` arrive sur Discord sans l'environnement entre crochets.
- **Cause** : le label `environment` est ajouté par Prometheus (`external_labels`). Une alerte injectée directement dans Alertmanager ne passe pas par Prometheus.
- **Correction** : `make alert-test` et `deploy.sh alert-test` lisent l'environnement dans le conteneur Prometheus et l'ajoutent eux-mêmes. Ne pas appeler `amtool alert add` à la main.

## Prometheus, Alertmanager et Grafana ne relisent pas leur configuration

- **Symptôme** : une règle d'alerte ou un tableau de bord modifié dans le dépôt n'est pas pris en compte après `docker compose up -d`.
- **Cause** : ces fichiers sont montés en lecture seule et lus au démarrage ; Compose ne recrée pas un conteneur dont seule la configuration montée a changé.
- **Correction** : `deploy.sh` recrée ces trois services à chaque mise en service. En local : `make down && make obs-up`.

## Grafana 13.2 et système de fichiers en lecture seule

- **Symptôme** : la source de données Prometheus est absente au démarrage de Grafana.
- **Cause** : Grafana tente de retélécharger ses plugins intégrés, ce qui échoue en lecture seule.
- **Correction** : `GF_PLUGINS_PREINSTALL_DISABLED=true` (déjà dans `compose.observability.yml`).
