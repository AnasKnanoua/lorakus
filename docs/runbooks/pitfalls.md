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

## `pg_dump` refuse de lire les tables à RLS forcée

- **Symptôme** : `pg_dump: error: query would be affected by row-level security policy for table …`, sauvegarde en échec.
- **Cause** : `pg_dump` désactive la RLS par défaut et s'arrête si elle s'appliquerait quand même. Avec `FORCE ROW LEVEL SECURITY`, elle s'applique aussi au propriétaire des tables.
- **Correction** : `pg_dump --enable-row-security` (déjà dans `infra/backup/lorakus-backup.sh`). La politique de `lorakus_migrator` lui laisse tout lire : la sauvegarde est complète. Trouvé en test avant la mise en production de la PR 23.
- **Retour arrière** : revenir à une version antérieure à la PR 23 garde le schéma (RLS forcée) mais remet l'ancienne image de sauvegarde, sans l'option : la sauvegarde quotidienne échoue jusqu'au redéploiement suivant. Le redéploiement lui-même fonctionne : depuis le 2026-11-11, la sauvegarde avant migration utilise l'image de la **nouvelle** version (trouvé par le staging, qui rejoue justement ce retour arrière).

## Une variable donnée au mauvais service

- **Symptôme** : le staging refuse la nouvelle version (`container lorakus-api-1 is unhealthy`), alors que les tests passent et que l'API démarre bien hors de Docker.
- **Cause** (2026-11-11) : `LORAKUS_FIELD_ENCRYPTION_KEY` avait été ajoutée à l'environnement de `postgres` au lieu de `api`. Sans la clé, l'API refuse de démarrer en staging et en production, comme prévu. En prime, la clé sortait de son périmètre.
- **Correction** : la clé est dans le service `api`. `tests/unit/test_compose_environment.py` vérifie désormais quels services reçoivent chaque secret. `deploy.sh` affiche aussi les journaux de la version refusée avant de la remplacer : la cause est visible dans le job `staging`.

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

## Trivy signale une « clé de compte Google » dans une bibliothèque

- **Symptôme** : `Vulnerabilites critiques corrigeables (bloquant)` échoue avec `CRITICAL: Google (gcp-service-account)` dans des fichiers de `site-packages`, alors qu'aucune vulnérabilité n'est listée.
- **Cause** (2026-11-12, PR 32) : l'analyse des secrets de Trivy est active dans `trivy image`. Sa règle `gcp-service-account` cherche le texte `"type": "service_account"`, que la documentation du SDK Anthropic 2.3 cite comme exemple (API beta « agents »).
- **Correction** : exception dans `infra/ci/trivy-secret.yaml`, passée à l'étape « Secrets dans l'image » par `--secret-config`. Une exception de Trivy porte soit sur un chemin, soit sur le texte, jamais les deux ensemble ; une exception par texte masquerait aussi les vraies clés (même texte). Elle est donc limitée aux dossiers concernés du code tiers. Vérifié : une vraie forme de clé ailleurs, y compris dans le reste du SDK, reste bloquante.
- **À ne pas faire** : supprimer l'étape « Secrets dans l'image » (l'image ne serait plus analysée pour un `.env` ou une clé embarqués par erreur), ou désactiver la règle `gcp-service-account` (une vraie clé Google ne serait plus signalée que par sa clé privée).
- **Depuis le 2026-11-12** : les secrets ont leur propre étape, bloquante dès HIGH (règle `private-key` comprise) ; les étapes de vulnérabilités utilisent `--scanners vuln`.
