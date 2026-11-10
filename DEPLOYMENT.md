# Déploiement

État au 2026-11-10 : en production sur `lorakus-prod`, sauvegarde quotidienne active, retour arrière essayé. Le staging et la sentinelle externe (VM Azure) restent à créer. En cas d'incident : [`docs/runbooks/`](docs/runbooks/README.md).

## 1. Environnements

Décision : [ADR 0036](docs/adr/0036-environments.md).

| Environnement | Hôte | Contenu | Données |
| --- | --- | --- | --- |
| Développement | Dell (Ubuntu) | `compose.yml`, `compose.dev.yml`, `compose.observability.yml` | Synthétiques |
| Staging | VM ARM Azure for Students (à créer) | Pile réduite, dimensionnée à la création de la VM | Synthétiques |
| Sentinelle externe | Même VM Azure (à créer) | Vérifie de l'extérieur que la production répond | Aucune |
| Production | `oracleworker` (Oracle Always Free, ARM, 1 OCPU, 6 Go, Oracle Linux 9), alias SSH `lorakus-prod`, dédié à Lorakus | API, PostgreSQL, pile d'observabilité, sauvegardes | Réelles |
| Red Team | À redimensionner en phase 17 | ZAP, Promptfoo | Aucune donnée de production |

`oraclevps` héberge Anime Notif : il est hors du périmètre de Lorakus et ne doit jamais être modifié.

Aucune exposition publique avant la phase 3 : l'API s'atteint par tunnel SSH. Adresses prévues ensuite : `app.lorakus.app` et `staging.lorakus.app`.

## 2. Prérequis d'un hôte

Réalisé sur `lorakus-prod` :

- Système à jour ; `dnf-automatic` limité aux mises à jour de sécurité.
- Docker Engine et plugin Compose, avec rotation des journaux, `live-restore` et `no-new-privileges`.
- Utilisateur `deploy` (groupe `docker`), clé SSH dédiée au déploiement ; SSH par clé uniquement.
- `firewalld` limité à SSH ; les ports 80 et 443 y seront ouverts en phase 3. Liste de sécurité Oracle : 22, 80, 443 et ICMP.
- Répertoire `/opt/lorakus` : fichier Compose, `.env` (600, `deploy`), volumes nommés.
- Nom d'hôte persistant (section 2.1).

À faire en phase 3 : enregistrements DNS chez Name.com (TLS terminé par le reverse proxy). Name.com ne gère pas les enregistrements CAA.

### 2.1 Nom d'hôte sur une image Oracle Linux

Trois mécanismes peuvent réécrire le nom d'hôte au démarrage. Le troisième, propre à Oracle, écrase les deux autres : le script `oci-dhclient.sh` réapplique à chaque événement réseau le nom saisi à la création de l'instance.

| Mécanisme | Réglage |
| --- | --- |
| cloud-init | `preserve_hostname: true` dans `/etc/cloud/cloud.cfg.d/zz-lorakus-hostname.cfg` |
| NetworkManager | `hostname-mode=none` dans `/etc/NetworkManager/conf.d/99-lorakus-hostname.conf` |
| Script Oracle | `PRESERVE_HOSTINFO=2` dans `/etc/oci-hostname.conf` |

Avec la valeur `2`, Oracle ne met plus `/etc/hosts` à jour : y corriger l'alias à la main, puis `hostnamectl set-hostname <nom>` et redémarrer. Vérification : `hostnamectl --static` après le redémarrage, et la ligne « Skip updating hostname » dans `journalctl -b`.

## 3. Images publiées

Le workflow `publish.yml` construit les images API et sauvegarde sur une machine de chaque architecture (amd64 et arm64), les teste (`infra/ci/smoke-image.sh`), les analyse avec Trivy, puis, sur `main` uniquement, les publie sur GHCR et les réunit sous l'étiquette `sha-<commit>`. L'empreinte (`@sha256:…`) de chaque image figure dans le résumé de l'exécution.

- Les deux paquets GHCR sont **publics** (réglage irréversible) : le serveur les télécharge sans identifiant.
- Une image n'est republiée que si son code change ; le déploiement prend le dernier commit de `main` qui a touché ces chemins.
- Première publication d'une **nouvelle** image : les jobs amd64 et arm64 peuvent créer le paquet en même temps et l'un est refusé (`denied`). Relancer le job échoué (`gh run rerun <id> --failed`) suffit.

## 4. Déploiement

Le workflow `deploy.yml`, lancé à la main, attend l'approbation de l'environnement GitHub `production`. Il se connecte au serveur en vérifiant son empreinte SSH, avec une clé qui ne peut exécuter que `infra/deploy/deploy.sh` (option `command=` de `authorized_keys`).

```bash
gh workflow run deploy.yml -f action=deploy     # ou rollback, status
```

`deploy.sh` désigne la configuration par un commit de `main` (copie du dépôt dans `/opt/lorakus/app`) et le code par l'empreinte des images. Séquence : vérification que le commit appartient à `main` → téléchargement des images → sauvegarde de la base (sauf au premier déploiement) → migrations → démarrage de tous les services → test de `/api/health/ready`. Si une étape échoue après le téléchargement, la version précédente est remise en service automatiquement.

Fichiers sur le serveur, dans `/opt/lorakus` : `.env` (secrets, 600, créé par `infra/deploy/init-env.sh`), `release.env` (version en service), `release.previous.env` (version précédente), `app/` (copie du dépôt).

Jamais d'image `latest`. Aucune mise à jour automatique non contrôlée en production.

Mesuré le 2026-11-10 : déploiement complet en 26 secondes. En cas d'échec : [runbook](docs/runbooks/deploy-failed.md).

### 4.1 Mise en place (une fois)

Sur le serveur, en tant que `deploy` : `git clone` du dépôt dans `/opt/lorakus/app`, puis `infra/deploy/init-env.sh`. Les mots de passe internes sont tirés au hasard sur place ; le webhook Discord, la clé B2 et la clé publique `age` sont saisis au clavier ; une valeur existante n'est jamais modifiée.

Côté GitHub, environnement `production` : approbation obligatoire, branche `main` seule ; secrets `DEPLOY_SSH_KEY` et `DEPLOY_HOST` ; variable `DEPLOY_KNOWN_HOSTS` (empreinte publique du serveur, vérifiée contre `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).

## 5. Migrations en production

- Le conteneur `migrate` exécute `alembic upgrade heads` avant le démarrage de l'API.
- Expand/contract (ADR 0011) : la version N fonctionne avec le schéma N+1 ; la contraction arrive à la version suivante, après une semaine sans incident.
- Une migration irréversible exige une sauvegarde vérifiée juste avant.

## 6. Retour arrière

`gh workflow run deploy.yml -f action=rollback` remet en service la version précédente (configuration et images), sans rejouer de migration : le schéma reste compatible grâce à l'expand/contract. Si une migration doit être annulée, la voie sûre est la [restauration](docs/runbooks/restore.md) de la sauvegarde faite juste avant le déploiement.

Essayé en production le 2026-11-10 : retour arrière en 10 secondes. Après un retour arrière, les deux versions sont échangées : un second `rollback` ramène la version défectueuse.

## 7. Sauvegardes et restauration

| Élément | Méthode | Fréquence | Destination | Rétention |
| --- | --- | --- | --- | --- |
| PostgreSQL | `pg_dump` chiffré avec `age` (`infra/backup/lorakus-backup.sh`) | Quotidienne vers 03:30 UTC (minuteur `lorakus-backup.timer`) et avant chaque migration | Backblaze B2, dossier `daily/` | Règles de cycle de vie du bucket |
| Fichiers utilisateur | À définir avec le port `BlobStore` (ADR 0024) | — | — | — |
| Configuration | Dépôt Git ; secrets uniquement sur le serveur | À chaque changement | GitHub | — |

- Le serveur ne détient que la clé **publique** `age` : il peut chiffrer, jamais déchiffrer. La clé privée reste dans le gestionnaire de mots de passe.
- Aucune clé B2 n'a le droit de suppression : une machine compromise ne peut pas effacer les sauvegardes. La rotation est faite par le bucket. Chaque machine a sa propre clé (section 7.2).
- `make restore-test` restaure la dernière sauvegarde dans une base jetable sans réseau et la vérifie.
- Métriques écrites pour node_exporter (collecteur textfile) ; alertes `LorakusBackupFailed`, `LorakusBackupMissing` (aucune réussite depuis 26 h) et `LorakusBackupNeverRecorded`.
- Sauvegarde à la main : `/opt/lorakus/app/infra/deploy/deploy.sh backup` (en tant que `deploy`). Elle attend la fin d'un déploiement en cours, 30 minutes au plus.
- Sauvegarde en échec : [runbook](docs/runbooks/backup-failed.md). Restauration en production : [runbook](docs/runbooks/restore.md).

### 7.1 Installer le minuteur (une fois, puis à chaque changement de `infra/systemd/`)

Les unités sont **copiées** dans `/etc/systemd/system` (et non liées) : une modification du dépôt ne change pas ce que systemd exécute sans une réinstallation volontaire.

```bash
sudo install -m 644 /opt/lorakus/app/infra/systemd/lorakus-backup.service /opt/lorakus/app/infra/systemd/lorakus-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lorakus-backup.timer
systemctl list-timers lorakus-backup.timer
```

Journal d'une exécution : `journalctl -u lorakus-backup.service -n 50`.

### 7.2 Une clé B2 par machine

Décision du 2026-11-10 : la clé partagée entre le Dell et le serveur est remplacée par une clé par machine, limitée au bucket des sauvegardes et à ce que la machine fait réellement.

| Machine | Nom de la clé | Droits | Usage |
| --- | --- | --- | --- |
| `lorakus-prod` | `lorakus-prod-backup` | `listBuckets`, `listFiles`, `readFiles`, `writeFiles` | Envoyer les sauvegardes, copie mensuelle |
| Dell | `lorakus-dell-restore` | `listBuckets`, `listFiles`, `readFiles` | `make restore-test`, restauration |

- Une clé volée se révoque sans toucher à l'autre machine, et le journal de Backblaze dit quelle machine a fait quoi.
- Le Dell n'écrit plus dans le bucket de production : une sauvegarde de développement ne peut plus passer pour la dernière sauvegarde de production. `make backup` sur le Dell demande donc un bucket d'essai distinct (`B2_BUCKET` et une clé à lui dans le `.env` local).
- Le serveur garde `readFiles` : la copie mensuelle se fait de fichier à fichier côté Backblaze. Le retirer n'apporterait rien, le serveur détient déjà les données en clair et les sauvegardes sont chiffrées avec une clé qu'il n'a pas.
- Le site de Backblaze ne sait pas créer une clé « lecture et écriture sans suppression » : passer par la CLI `b2` (v4), depuis une machine autorisée avec la clé maîtresse.

```bash
b2 key create --bucket <bucket> lorakus-prod-backup listBuckets,listFiles,readFiles,writeFiles
b2 key create --bucket <bucket> lorakus-dell-restore listBuckets,listFiles,readFiles
```

Mise en place sur le serveur : [runbook, « Remplacer la clé B2 du serveur »](docs/runbooks/backup-failed.md). Sur le Dell : remplacer `B2_KEY_ID` et `B2_APP_KEY` dans `.env`, puis `make restore-test`. Supprimer l'ancienne clé partagée une fois les deux vérifications réussies.

## 8. Accès d'administration

Grafana, Prometheus et Alertmanager ne sont pas exposés publiquement : accès par tunnel SSH, par exemple `ssh -L 3000:localhost:3000 lorakus-prod`.

## 9. Changer d'hébergeur

Déclencheurs : mémoire insuffisante, récupération de l'instance par Oracle, ouverture à plusieurs utilisateurs. Cible documentée : Hetzner ARM.

1. Préparer l'hôte (section 2).
2. Générer de nouveaux secrets sur le nouvel hôte ; y placer la clé publique `age` et une clé B2 limitée.
3. Restaurer la dernière sauvegarde.
4. Basculer le DNS, vérifier, supprimer l'ancien hôte après 7 jours.

Durée cible : une soirée.

## 10. Checklist après déploiement

- [ ] `/api/health/ready` vert, empreinte de l'image attendue
- [ ] Aucune erreur 5xx dans les 10 minutes
- [ ] Alerte de test reçue sur Discord avec `[production]` dans le titre et un lien vers le runbook : `/opt/lorakus/app/infra/deploy/deploy.sh alert-test` sur le serveur. Ne pas utiliser `amtool alert add` directement : une alerte injectée dans Alertmanager ne passe pas par Prometheus et ne reçoit pas le label `environment`
- [ ] Sauvegarde du jour présente, métriques à jour
- [ ] `PROJECT_STATE.md` et `CHANGELOG.md` à jour
