# Déploiement

État au 2026-11-18 : en production sur `lorakus-prod` (PR 41 déployée), sauvegarde quotidienne active, retour arrière essayé. Staging éphémère dans la CI et sentinelle externe healthchecks.io (ADR 0037). En cas d'incident : [`docs/runbooks/`](docs/runbooks/README.md).

## 1. Environnements

Décisions : [ADR 0036](docs/adr/0036-environments.md), amendée par l'[ADR 0037](docs/adr/0037-ci-staging-external-sentinel.md).

| Environnement | Hôte | Contenu | Données |
| --- | --- | --- | --- |
| Développement | Dell (Ubuntu) | `compose.yml`, `compose.dev.yml`, `compose.observability.yml` | Synthétiques |
| Staging | Runner GitHub ARM jetable, avant chaque déploiement (`infra/staging/staging-test.sh`) | Pile complète de production, B2 remplacé par un dossier local | Synthétiques |
| Sentinelle externe | healthchecks.io (formule gratuite) | Reçoit le signal de vie de la production, prévient Discord s'il cesse | Aucune |
| Production | `oracleworker` (Oracle Always Free, ARM, 1 OCPU, 6 Go, Oracle Linux 9), alias SSH `lorakus-prod`, dédié à Lorakus | API, PostgreSQL, pile d'observabilité, sauvegardes | Réelles |
| Red Team | À redimensionner en phase 17 | ZAP, corpus d'injections | Aucune donnée de production |

`oraclevps` héberge Anime Notif : il est hors du périmètre de Lorakus et ne doit jamais être modifié.

Depuis la PR 35 (ADR 0038), seul Caddy (service `web`) est publié : `https://app.lorakus.app` (interface et API à la même origine). Tout le reste (API `127.0.0.1:8001`, Prometheus, Grafana, Alertmanager) n'est joignable que depuis le serveur ou par tunnel SSH. `staging.lorakus.app` n'existe pas : le staging est éphémère, dans la CI (ADR 0037).

## 2. Prérequis d'un hôte

Réalisé sur `lorakus-prod` :

- Système à jour ; `dnf-automatic` limité aux mises à jour de sécurité.
- Docker Engine et plugin Compose, avec rotation des journaux, `live-restore` et `no-new-privileges`.
- Utilisateur `deploy` (groupe `docker`), clé SSH dédiée au déploiement ; SSH par clé uniquement.
- `firewalld` : SSH, HTTP et HTTPS (section 4.6). Liste de sécurité Oracle : 22, 80, 443 et ICMP.
- Répertoire `/opt/lorakus` : fichier Compose, `.env` (600, `deploy`), volumes nommés.
- Nom d'hôte persistant (section 2.1).

DNS chez Name.com (fait le 2026-11-12) : un seul enregistrement `A` `app` vers l'adresse publique du serveur, TTL 300 ; enregistrements de stationnement supprimés ; aucun `AAAA` (le serveur n'a pas d'IPv6, Let's Encrypt l'essaierait en premier). Name.com ne gère pas les enregistrements CAA.

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
- L'image de l'API contient le modèle d'embeddings (`/app/models/multilingual-e5-small`, environ 135 Mo de plus, ADR 0007) : il est téléchargé à la construction et vérifié par SHA-256, puis le test de fumée le charge et affiche sa mémoire et sa latence sur chaque architecture (journal du job, étape du test de fumée).
- Première publication d'une **nouvelle** image : les jobs amd64 et arm64 peuvent créer le paquet en même temps et l'un est refusé (`denied`). Relancer le job échoué (`gh run rerun <id> --failed`) suffit.

## 4. Déploiement

Le workflow `deploy.yml`, lancé à la main, rejoue d'abord le déploiement sur un staging jetable (section 4.4), puis attend l'approbation de l'environnement GitHub `production`. Il se connecte au serveur en vérifiant son empreinte SSH, avec une clé qui ne peut exécuter que `infra/deploy/deploy.sh` (option `command=` de `authorized_keys`).

```bash
make deploy          # ou make rollback, make prod-status (gh workflow run deploy.yml -f action=...)
```

`deploy.sh` désigne la configuration par un commit de `main` (copie du dépôt dans `/opt/lorakus/app`) et le code par l'empreinte des images. Séquence : vérification que le commit appartient à `main` → téléchargement des images → sauvegarde de la base (sauf au premier déploiement) → migrations → démarrage de tous les services → test de `/api/health/ready`. Si une étape échoue après le téléchargement, la version précédente est remise en service automatiquement.

Fichiers sur le serveur, dans `/opt/lorakus` : `.env` (secrets, 600, créé par `infra/deploy/init-env.sh`), `release.env` (version en service), `release.previous.env` (version précédente), `app/` (copie du dépôt).

Jamais d'image `latest`. Aucune mise à jour automatique non contrôlée en production.

Mesuré le 2026-11-10 : déploiement complet en 26 secondes. En cas d'échec : [runbook](docs/runbooks/deploy-failed.md).

### 4.1 Mise en place (une fois)

Sur le serveur, en tant que `deploy` : `git clone` du dépôt dans `/opt/lorakus/app`, puis `infra/deploy/init-env.sh`. Les mots de passe internes sont tirés au hasard sur place ; le webhook Discord, la clé B2, la clé publique `age`, l'adresse healthchecks.io et la clé d'API Anthropic sont saisis au clavier ; une valeur existante n'est jamais modifiée.

Côté GitHub, environnement `production` : approbation obligatoire, branche `main` seule ; secrets `DEPLOY_SSH_KEY` et `DEPLOY_HOST` ; variable `DEPLOY_KNOWN_HOSTS` (empreinte publique du serveur, vérifiée contre `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`).

### 4.2 Compte propriétaire (une fois)

Pas d'inscription publique : le compte propriétaire est créé sur le serveur, après le déploiement qui apporte l'identité. La commande demande l'adresse puis le mot de passe deux fois, sans l'afficher.

```bash
ssh -t lorakus-prod 'sudo -iu deploy /opt/lorakus/app/infra/deploy/deploy.sh compose run --rm --no-deps api python -m lorakus.cli create-owner'
```

Un second appel est refusé : il n'y a qu'un propriétaire.

### 4.3 Clé de chiffrement des champs

`LORAKUS_FIELD_ENCRYPTION_KEY` chiffre les secrets de double authentification en base. Elle est créée automatiquement dans `/opt/lorakus/.env` au premier déploiement qui en a besoin (`deploy.sh` lance `init-env.sh --generated-only` à chaque déploiement). Elle **n'est pas dans les sauvegardes** : après ce déploiement, la copier une fois dans le gestionnaire de mots de passe.

```bash
ssh lorakus-prod 'sudo -iu deploy grep ^LORAKUS_FIELD_ENCRYPTION_KEY= /opt/lorakus/.env'
```

Sans elle, une base restaurée sur un serveur neuf garde ses comptes mais perd la double authentification : `python -m lorakus.cli recover-second-factor`, puis `python -m lorakus.cli enable-second-factor` (en production, la connexion est impossible entre les deux).

`LORAKUS_CONNECTOR_ENCRYPTION_KEY` (PR 45, ADR 0041) chiffre les adresses secrètes des calendriers ICS. Créée de la même façon, au premier déploiement de la PR 45 ; donnée à l'API **et au worker** (qui synchronise), jamais la clé précédente. L'API et le worker refusent de démarrer sans elle en staging et en production. Hors sauvegardes elle aussi ; la perdre oblige seulement à supprimer les abonnements et à recopier leurs adresses : la copier dans le gestionnaire de mots de passe est conseillé, pas indispensable.

`LORAKUS_VAPID_PRIVATE_KEY` et `LORAKUS_VAPID_PUBLIC_KEY` (P5, ADR 0042) : la paire des notifications Web Push (courbe P-256, en hexadécimal), créée par `init-env.sh` avec OpenSSL au premier déploiement de la PR 52, sans rien demander. La privée va au seul **worker** (qui envoie), la publique à l'API (donnée aux navigateurs) et au worker ; une paire incohérente empêche le worker de démarrer. Absentes : pas de notification, les cartes « À noter » restent. Hors sauvegardes ; la perdre oblige seulement à réactiver les notifications sur chaque appareil (page « Notifications »). Ne jamais la régénérer sans raison : chaque appareil devrait se réabonner.

### 4.4 Staging éphémère

Avant chaque `deploy`, le job `staging` (runner ARM, même architecture que la production) installe la version en production, y écrit une donnée témoin, déploie la nouvelle version par-dessus avec le vrai `deploy.sh`, essaie le retour arrière, redéploie, lance une sauvegarde et une alerte de test, puis restaure la dernière sauvegarde en suivant le [runbook](docs/runbooks/restore.md) et vérifie la donnée témoin. S'il échoue, la production n'est pas touchée.

- « Version en production » = commit du dernier run « Deploy (deploy) » réussi.
- B2 est remplacé par un dossier local grâce à `compose.host.yml` (copie de `infra/staging/compose.staging.yml`). Ce fichier n'existe pas en production.
- Urgence absolue seulement : `make deploy-skip-staging`, à consigner dans une note d'incident.

### 4.5 Sentinelle externe (une fois)

1. Sur healthchecks.io : une vérification `lorakus-prod`, période 2 minutes, tolérance 5 minutes ; intégration Discord vers `#lorakus-infra`.
2. Sur le serveur, en tant que `deploy` : `/opt/lorakus/app/infra/deploy/init-env.sh` demande l'adresse de ping (`HEALTHCHECKS_PING_URL`), puis `make deploy` depuis le Dell (ou `deploy.sh compose up -d --force-recreate alertmanager`).
3. Vérifier : healthchecks.io passe à « up » en moins de 3 minutes. Puis tester une vraie disparition ([runbook](docs/runbooks/production-down.md#tester-la-sentinelle-après-chaque-changement-de-la-chaîne-dalerte)).

### 4.6 Exposition publique (PR 35, une fois)

Avant le premier déploiement qui apporte Caddy, vérifier qu'aucun réseau Docker n'occupe déjà `172.31.250.0/24`, et qu'aucun programme n'écoute déjà sur les ports 80 et 443 (`sudo ss -ltnp 'sport = :80 or sport = :443'` ne doit rien afficher) (réseau `edge` de `compose.prod.yml`) :

```bash
ssh lorakus-prod 'docker network inspect $(docker network ls -q) --format "{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}"'
```

Après le déploiement, ouvrir HTTP et HTTPS dans `firewalld` (Docker publie ses ports en contournant `firewalld` ; cette règle rend la configuration explicite et cohérente avec la liste de sécurité Oracle) :

```bash
ssh -t lorakus-prod 'sudo firewall-cmd --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload && sudo firewall-cmd --list-services'
```

Puis activer la double authentification du propriétaire (obligatoire en production pour se connecter). La commande affiche une clé à saisir dans une application d'authentification, demande un code, puis affiche les codes de secours, à ranger dans le gestionnaire de mots de passe :

```bash
ssh -t lorakus-prod 'sudo -iu deploy /opt/lorakus/app/infra/deploy/deploy.sh compose exec api python -m lorakus.cli enable-second-factor'
```

Vérifications depuis le Dell : `curl -sI https://app.lorakus.app/ | head -3` (HTTP/2 200), puis sur le téléphone, installer l'application depuis Chrome (« Ajouter à l'écran d'accueil »). Les journaux de Caddy doivent montrer les vraies adresses des visiteurs (`dc logs --tail 20 web`), pas une adresse en `172.`.

## 5. Migrations en production

- Le conteneur `migrate` exécute `alembic upgrade heads` avant le démarrage de l'API.
- Expand/contract (ADR 0011) : la version N fonctionne avec le schéma N+1 ; la contraction arrive à la version suivante, après une semaine sans incident.
- Une migration irréversible exige une sauvegarde vérifiée juste avant.

## 6. Retour arrière

`make rollback` remet en service la version précédente (configuration et images), sans rejouer de migration : le schéma reste compatible grâce à l'expand/contract. Si une migration doit être annulée, la voie sûre est la [restauration](docs/runbooks/restore.md) de la sauvegarde faite juste avant le déploiement.

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

Grafana, Prometheus et Alertmanager ne sont pas exposés publiquement : accès par tunnel SSH, par exemple `ssh -L 3000:localhost:3000 lorakus-prod`. Tempo et Loki (PR 40) n'ont aucun port, même local : on les consulte dans Grafana (Explore), qui a leurs sources de données ; un identifiant de trace se copie depuis « Pourquoi ? » sous une réponse du chat ([runbook](docs/runbooks/observability.md)).

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
- [ ] healthchecks.io affiche `lorakus-prod` « up »
- [ ] Alerte de test reçue sur Discord avec `[production]` dans le titre et un lien vers le runbook : `/opt/lorakus/app/infra/deploy/deploy.sh alert-test` sur le serveur. Ne pas utiliser `amtool alert add` directement : une alerte injectée dans Alertmanager ne passe pas par Prometheus et ne reçoit pas le label `environment`
- [ ] Sauvegarde du jour présente, métriques à jour
- [ ] `PROJECT_STATE.md` et `CHANGELOG.md` à jour

### Clé d'API Anthropic (PR 33, D-D)

1. Console Anthropic : clé dédiée `lorakus-prod`, crédit prépayé, **rechargement automatique désactivé** (c'est le plafond global).
2. Après le déploiement de la PR 33 (qui apporte la nouvelle version du script), sur le serveur en tant que `deploy` : `/opt/lorakus/app/infra/deploy/init-env.sh` ne demande que la clé (saisie masquée, format vérifié).
3. Redémarrer l'API pour qu'elle la lise : `dc up -d --force-recreate api` (raccourci `dc` : `docs/runbooks/README.md`).

Sans clé, l'assistant répond par son message de secours ; la clé ne va qu'au service `api` (test `test_compose_environment.py`). Rotation ou fuite : `docs/runbooks/ai.md`.

### Mémoire du modèle d'embeddings (PR 37a)

Mesure faite après le déploiement de la PR 37a, sur le serveur en tant que `deploy` (raccourci `dc` : `docs/runbooks/README.md`) :

```bash
dc run --rm -T --no-deps api python -m lorakus.ai.providers.check </dev/null && docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' && free -m
```

La première commande lance un conteneur jetable de la même image (jamais `dc exec` dans `api` : une seconde copie du modèle sous la même limite (832 Mo depuis la PR 41) pourrait faire tuer l'API) et affiche la mémoire de ce seul conteneur ; la seconde donne la mémoire réelle du conteneur `api`, modèle compris. À refaire à chaque changement de modèle : reporter les chiffres ici et dans `PROJECT_STATE.md`, puis ajuster la limite de l'API (`compose.yml`) et le seuil de `LorakusApiHighMemory` en gardant au moins 30 % de marge au repos.

Mesures du 2026-11-13 (`oracleworker`, ARM) : chargement 1,66 s ; le modèle ajoute environ 407 Mo à un processus (123 → 530 Mo) ; API au repos 545 Mo sur 768 ; question 33 ms en médiane et 38 ms au 95e centile ; 32 faits en 623 ms ; hôte 2,4 Go utilisés et 3,2 Go disponibles sur 5,6. Conséquences : limite de l'API gardée à 768 Mo (la baisser laisserait moins de 30 % de marge), `LorakusApiHighMemory` à 650 Mo ; Grafana, à 325 Mo pour 384, passe à 512 Mo.

Mesures du 2026-11-14, après la PR 40 (traces et journaux) : API 566 Mo sur 768 (+21 Mo pour OpenTelemetry), Tempo 112 Mo sur 256, Loki 72 Mo sur 256, Grafana 322 Mo sur 512 ; hôte 2,4 Go utilisés sur 5,6 (3,2 Go disponibles). Conséquences (PR 41) : limite de l'API portée à 832 Mo pour retrouver environ 30 % de marge en service (32 %), `LorakusApiHighMemory` à 700 Mo ; Tempo et Loki gardent 256 Mo (plus de 50 % de marge).

Mesures du 2026-11-18, après la PR 41 : voir « Mémoire des conteneurs » ci-dessous.

### Mémoire des conteneurs : `docker stats` et `memory.stat`

`docker stats` additionne deux sortes de mémoire. La mémoire **anonyme** (`anon`) est celle du programme lui-même : ses structures, son tas ; le noyau ne peut pas la jeter. Le **cache de fichiers** (`file`) garde en mémoire des morceaux de fichiers lus ou écrits ; quand le conteneur approche de sa limite, le noyau le reprend avant de tuer quoi que ce soit. Pour un service qui écrit beaucoup sur disque (Tempo, Loki, Prometheus), `docker stats` peut donc approcher la limite sans aucun danger. Les alertes `LorakusApiHighMemory` et `LorakusWorkerHighMemory` lisent la mémoire résidente du processus (`process_resident_memory_bytes`), qui ne compte pas ce cache.

Mesure, sur le serveur en tant que `deploy`, après le bloc « Session » de [`docs/runbooks/README.md`](docs/runbooks/README.md) (cgroups v2, ceux d'Oracle Linux 9 ; aucune commande ne passe par `sudo`) :

```bash
for s in api worker tempo loki prometheus grafana; do pid=$(docker inspect -f '{{.State.Pid}}' "$(dc ps -q "$s")") && cg=$(awk -F: '$1=="0"{print $3}' "/proc/$pid/cgroup") && awk -v s="$s" '$1=="anon"{a=$2} $1=="file"{f=$2} $1=="slab"{k=$2} END{printf "%-11s anon %4d Mo  file %4d Mo  slab %3d Mo\n", s, a/1048576, f/1048576, k/1048576}' "/sys/fs/cgroup$cg/memory.stat"; done && docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' && free -m
```

Règle : une limite se décide d'après `anon` (plus `slab`, la mémoire du noyau comptée au conteneur, par prudence), avec au moins 30 % de marge au repos ; `docker stats` sert à repérer un service à examiner, pas à fixer sa limite. Le swap de l'hôte (`free -m`) se surveille à part : s'il grossit d'une mesure à l'autre, la mémoire manque vraiment.

Mesures du 2026-11-18 (`docker stats`, utilisé / limite) :

| Service | Mesuré | Limite | Remarque |
| --- | --- | --- | --- |
| `api` | 545 Mo | 832 Mo | 34 % de marge ; alerte à 700 Mo |
| `worker` | 80 Mo | 256 Mo | — |
| `tempo` | 233 Mo | 256 Mo | `anon` 121 Mo, `file` 50 Mo : limite gardée |
| `loki` | 98 Mo | 256 Mo | — |
| `prometheus` | 122 Mo | 300 Mo | — |
| `grafana` | 253 Mo | 512 Mo | — |

Hôte : 2,3 Go utilisés sur 5,6, 3,3 Go disponibles, 531 Mo de swap utilisés. Conséquence : aucune limite ne change. Tempo est à 91 % de sa limite selon `docker stats`, mais sa mémoire anonyme laisse plus de 50 % de marge ; à remesurer avec la commande ci-dessus après chaque montée de version de Tempo, Loki ou Prometheus, ou si `docker inspect` signale un `OOMKilled`.
