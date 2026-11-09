# Déploiement

État au 2026-11-09 : l'hôte de production est préparé, rien n'y est encore déployé. Les sections marquées « PR n°16 » ou « PR n°17 » décrivent la cible ; elles seront complétées par ces PR.

## 1. Environnements

Décision : [ADR 0036](docs/adr/0036-environments.md).

| Environnement | Hôte | Contenu | Données |
| --- | --- | --- | --- |
| Développement | Dell (Ubuntu) | `compose.yml`, `compose.dev.yml`, `compose.observability.yml` | Synthétiques |
| Staging | VM ARM Azure for Students (PR n°17) | Pile réduite, dimensionnée à la création de la VM | Synthétiques |
| Sentinelle externe | Même VM Azure (PR n°17) | Vérifie de l'extérieur que la production répond | Aucune |
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

## 3. Premier déploiement (PR n°16)

1. Générer les secrets **sur le serveur**, par un script, dans `/opt/lorakus/.env` (600). GitHub ne connaît que la clé SSH de déploiement.
2. Récupérer les images publiées sur GHCR, désignées par leur empreinte.
3. Appliquer les migrations, puis démarrer la pile en attendant que les conteneurs soient sains.
4. Vérifier `/api/health/ready`, le tableau Grafana (par tunnel SSH) et la réception d'une alerte de test sur Discord.
5. Lancer une sauvegarde puis le test de restauration.

## 4. Mise à jour

| Environnement | Déclencheur | Séquence |
| --- | --- | --- |
| Production (PR n°16) | Workflow GitHub, approbation manuelle de l'environnement `production` | Connexion SSH en tant que `deploy` avec vérification de l'empreinte de l'hôte → image désignée par son empreinte → migrations → démarrage → test de `/api/health/ready` |
| Staging (PR n°17) | À définir avec la VM Azure | Même séquence, sans approbation |

Jamais d'image `latest` : une image est toujours désignée par son empreinte (`@sha256:`). Aucune mise à jour automatique non contrôlée en production.

## 5. Migrations en production

- Le conteneur `migrate` exécute `alembic upgrade heads` avant le démarrage de l'API.
- Expand/contract (ADR 0011) : la version N fonctionne avec le schéma N+1 ; la contraction arrive à la version suivante, après une semaine sans incident.
- Une migration irréversible exige une sauvegarde vérifiée juste avant.

## 6. Retour arrière (PR n°16)

Une seule commande redéploie l'empreinte de l'image précédente ; le schéma reste compatible grâce à l'expand/contract. Si une migration doit être annulée : `alembic downgrade <révision>` puis redéploiement de l'image précédente, à documenter dans le runbook de restauration.

## 7. Sauvegardes et restauration

| Élément | Méthode | Fréquence | Destination | Rétention |
| --- | --- | --- | --- | --- |
| PostgreSQL | `pg_dump` chiffré avec `age` (`infra/backup/lorakus-backup.sh`) | Quotidienne par minuteur systemd (PR n°17) et avant chaque migration | Backblaze B2, dossier `daily/` | Règles de cycle de vie du bucket |
| Fichiers utilisateur | À définir avec le port `BlobStore` (ADR 0024) | — | — | — |
| Configuration | Dépôt Git ; secrets uniquement sur le serveur | À chaque changement | GitHub | — |

- Le serveur ne détient que la clé **publique** `age` : il peut chiffrer, jamais déchiffrer. La clé privée reste dans le gestionnaire de mots de passe.
- La clé B2 du serveur n'a pas le droit de suppression : une machine compromise ne peut pas effacer les sauvegardes. La rotation est faite par le bucket.
- `make restore-test` restaure la dernière sauvegarde dans une base jetable sans réseau et la vérifie.
- Métriques écrites pour node_exporter (collecteur textfile) ; alertes `LorakusBackupFailed`, `LorakusBackupMissing` (aucune réussite depuis 26 h) et `LorakusBackupNeverRecorded`.

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
- [ ] Une alerte de test reçue sur Discord
- [ ] Sauvegarde du jour présente, métriques à jour
- [ ] `PROJECT_STATE.md` et `CHANGELOG.md` à jour
