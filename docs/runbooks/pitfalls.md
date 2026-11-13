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

## Alembic ignore en silence un dossier de migrations absent

- **Symptôme** (évité avant la production, 2026-11-12, PR 33) : la migration se termine sans erreur, mais les tables d'un module manquent ; l'API démarre puis répond 500 sur les routes du module.
- **Cause** : `alembic.ini` cherche les migrations des modules dans `lorakus_modules/<id>/migrations` à côté de lui ; l'image ne les copiait pas (le code des modules est installé dans `.venv`). Alembic ne signale pas un dossier de `version_locations` absent.
- **Correction** : le Dockerfile copie les seuls fichiers de migration des modules dans `/app/lorakus_modules/` ; `alembic/env.py` refuse de migrer si un module installé déclare une branche introuvable. Vérifié en simulant l'image (wheel installée hors du dépôt).
- **Corollaire** : `alembic_version` a une ligne par branche (Core et chaque module).

## « commande | grep -q » échoue au hasard dans les scripts

- **Symptôme** (2026-11-12, PR 33) : « ECHEC : metrique des requetes absente » dans le test de fumée de l'image, sur une seule architecture, alors que la métrique est bien exposée.
- **Cause** : avec `set -o pipefail` (nos scripts, et toute étape `run:` de GitHub Actions), `grep -q` s'arrête à la première correspondance et ferme le tuyau ; si la commande de gauche écrit encore (le serveur de métriques envoie sa page en plusieurs morceaux), elle reçoit SIGPIPE et le tuyau entier est en échec. Mesuré : 12 à 22 échecs sur 50 essais contre une vraie API.
- **Correction** : lire la sortie d'abord, chercher ensuite : `page=$(curl -fsS …)` puis `grep -qF '…' <<<"$page"` (50 sur 50). Appliqué au test de fumée, à la CI, au test de restauration et au staging.
- **À ne pas faire** : écrire un nouveau `… | grep -q` dans un script ou un workflow.

## `.env` appartient à root après `init-env.sh`

- **Symptôme** (2026-11-12) : `docker compose` répond « permission denied » sur `/opt/lorakus/.env` ; le déploiement suivant échouerait.
- **Cause** : `init-env.sh` lancé avec `sudo` ; le script remplace le fichier, et le nouveau appartient à qui le lance (root).
- **Correction** : `sudo chown deploy:deploy /opt/lorakus/.env && sudo chmod 600 /opt/lorakus/.env`. Depuis la PR 34, le script refuse root et tout utilisateur autre que le propriétaire du fichier, et donne la bonne commande (`sudo -iu deploy …`).

## Docker publie ses ports en contournant `firewalld`

- **Constat** (2026-11-12, PR 35) : un port publié par Docker (`ports: "80:8080"`) est joignable depuis Internet même si `firewalld` ne l'autorise pas : Docker insère ses propres règles de redirection avant celles de `firewalld`. La liste de sécurité Oracle reste le seul filtre en amont.
- **Règle** : seul le service `web` (Caddy) publie un port sur toutes les interfaces ; tout autre `ports:` est lié à `127.0.0.1`. `firewalld` autorise tout de même `http` et `https` pour que sa configuration dise la vérité (DEPLOYMENT.md §4.6).
- **À ne pas faire** : ajouter un `ports:` sans `127.0.0.1:` devant, en croyant que `firewalld` le protège.

## Le premier déploiement d'une nouvelle option de `deploy.sh` passe par l'ancien script

- **Constat** (2026-11-12, PR 35) : la clé SSH de GitHub exécute le `deploy.sh` déjà présent sur le serveur, celui de la version en service. Ce script n'accepte que les arguments qu'il connaissait (trois empreintes avant la PR 35).
- **Solution** : `deploy.sh status` annonce `LORAKUS_DEPLOY_PROTOCOL` ; `deploy.yml` n'envoie l'empreinte web qu'à un script de protocole 2, sinon il déploie d'abord sans elle (ce qui installe le nouveau script), puis avec elle. Le staging rejoue ces deux passages.
- **À retenir** : toute nouvelle option de `deploy.sh` doit rester acceptée par l'ancien script, ou suivre le même schéma (numéro de protocole et deux passages).

## « exec /usr/bin/caddy: operation not permitted »

- **Symptôme** (2026-11-12, CI de la PR 35) : le conteneur `web` s'arrête aussitôt ; le test de fumée de l'image échoue sur les deux architectures.
- **Cause** : l'image officielle de Caddy pose la capacité de fichier `cap_net_bind_service` sur son binaire (`setcap`). Un programme qui porte une capacité absente de l'ensemble autorisé du conteneur (`cap_drop: ALL`) ne peut pas être lancé : le noyau refuse l'`exec`.
- **Correction** : notre image recopie le binaire sans attribut étendu (`install`) dans `/usr/local/bin` et supprime l'original. Caddy écoute sur 8080 et 8443, il n'a besoin d'aucune capacité.
- **À retenir** : toute image de base qui utilise `setcap` pose le même problème avec notre durcissement ; le test de fumée, qui lance l'image avec les mêmes options que Compose, le détecte.

## Caddy ne démarre pas : « Address already in use »

- **Symptôme** (2026-11-12, staging de la PR 35) : « failed to set up container networking: Address already in use » au démarrage de `web` ; le déploiement revient à la version précédente.
- **Cause** : le réseau `edge` n'avait pas de plage réservée. L'API et Prometheus, attachés au réseau avant Caddy (premier passage du déploiement), ont reçu les premières adresses libres, dont `172.31.250.2`, l'adresse fixe de Caddy.
- **Correction** : `ip_range` (`172.31.250.128/25`) limite l'attribution automatique à la moitié haute du réseau ; les adresses fixes (Caddy) sont prises dans la moitié basse.
- **Corrigé au passage** : en cas d'échec, `deploy.sh` supprimait `release.next.env` avant d'afficher les journaux de la version refusée (« couldn't find env file ») ; il le garde désormais jusque-là.

## Le retour arrière ramène l'étape intermédiaire d'un déploiement en deux passages

- **Symptôme** (2026-11-12, staging) : après le déploiement de la PR 35, `rollback` remet le même commit sans Caddy au lieu de la version d'avant.
- **Cause** : chaque passage réussi faisait de la version en service la « précédente ». Après deux passages, la précédente était donc le premier passage.
- **Correction** : un passage qui garde le même commit (images complétées) remplace la version en service sans toucher à la précédente. Le staging vérifie que le retour arrière revient bien à la version de production, sans Caddy quand elle n'en avait pas.

## « Image web introuvable » au déploiement juste après une fusion

- **Symptôme** (2026-11-13) : `make deploy` lancé juste après la fusion d'une PR qui ne touche que l'interface ; le staging échoue à « Trouver la version en production et la nouvelle version » : `Image web introuvable pour le commit … : le workflow Publish a-t-il reussi ?`. La production n'est pas touchée.
- **Cause** : `wait-publish.sh` ne connaissait que les chemins des images API et sauvegarde ; pour une fusion qui ne change que `frontend/` ou `infra/web/`, il répondait « rien à attendre » alors que Publish construisait encore l'image web.
- **Correction** : `wait-publish.sh` suit les chemins des trois images. Toute nouvelle image doit être ajoutée au même moment à `publish.yml` (déclencheurs), `resolve-images.sh` et `wait-publish.sh`.
- **En attendant** : `gh run watch "$(gh run list --workflow publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status`, puis relancer `make deploy`.

## ONNX Runtime envoie de la télémétrie à Microsoft

- **Constat** (2026-11-13, première mesure du modèle d'embeddings en production) : `[W:onnxruntime:Default, telemetry_1ds.cc:600] Failed to persist telemetry device ID; using an in-memory identifier`. La version Linux d'ONNX Runtime 1.31 embarque un collecteur Microsoft (1DS, `mobile.events.data.microsoft.com`) : à la première session, il crée un identifiant d'appareil et met un événement d'usage en file pour l'envoyer. L'API a un accès sortant (fournisseur d'IA) : rien ne l'en empêchait. Aucun texte de l'utilisateur n'y figure (statistiques techniques), mais cela contredit « rien ne sort » (ADR 0007).
- **Mesuré** (copie de travail, petit modèle ONNX) : sans réglage, `~/.cache/Microsoft/DeveloperTools/.onnxruntime/` contient `deviceid` et une base `onnxruntime.db` avec un événement en file. `onnxruntime.disable_telemetry_events()` appelé après l'import arrive **trop tard** (l'événement est déjà en file). Avec `ORT_DISABLE_TELEMETRY=1` posée **avant** l'import, rien n'est créé.
- **Correction** : `onnx_embedder.py` force `ORT_DISABLE_TELEMETRY=1` avant d'importer ONNX Runtime, et l'image pose la même variable (`backend/Dockerfile`). `tests/unit/test_embeddings.py::test_onnx_runtime_telemetry_never_starts` ouvre une session dans un processus neuf et vérifie qu'aucun fichier de télémétrie n'est créé (témoin sans protection inclus).
- **À retenir** : toute bibliothèque native ajoutée à l'API peut avoir sa propre télémétrie. Lire ses chaînes (`strings … | grep -i telemetry`) et ses variables d'environnement avant de l'adopter.

## Le staging échoue quand on redéploie la version déjà en production

- **Symptôme** (2026-11-13) : un second `make deploy` juste après un déploiement réussi échoue dans le job `staging`, à l'étape « 3/6 Retour arrière » : `ECHEC : aucune version precedente enregistree`. La production n'est pas touchée (un staging en échec bloque le job `production`).
- **Cause** : la version en production et la nouvelle version sont le même commit. `deploy.sh` complète alors la version en service sans en faire une version précédente (comportement voulu, voir « Le retour arrière ramène l'étape intermédiaire… ») ; sur l'hôte jetable, le retour arrière n'avait donc rien à retrouver.
- **Correction** : `staging-test.sh` reconnaît le redéploiement du même commit, saute le retour arrière (vérifié au déploiement de cette version) et vérifie qu'aucune version précédente n'a été créée ; le résumé du job l'indique. Mise à jour, sauvegarde et restauration restent vérifiées.
- **À retenir** : après un `make deploy` réussi, inutile de le relancer ; `make prod-status` montre la version en service.

## `dc: invalid option -- 'T'` sur le serveur

- **Symptôme** : une commande des runbooks qui commence par `dc` affiche l'aide d'un programme inconnu.
- **Cause** : `dc` n'est défini que dans la session ouverte par le bloc « Session » de `docs/runbooks/README.md`. Sans lui, le shell lance `dc`, la calculatrice de GNU installée sur Oracle Linux.
- **Correction** : coller d'abord le bloc « Session » (après `sudo -iu deploy`), puis la commande. Pour une commande isolée, `/opt/lorakus/app/infra/deploy/deploy.sh compose …` fait la même chose sans session.
