# Restaurer une sauvegarde en production

Procédure **destructive** : elle remplace toutes les données de la base par celles d'une sauvegarde. Tout ce qui a été écrit après la sauvegarde est perdu.

Préparer la session : [README](README.md#session).

## Quand l'utiliser

- Données corrompues ou supprimées par erreur.
- Volume PostgreSQL perdu, ou serveur reconstruit (`DEPLOYMENT.md` §9).
- Migration irréversible à annuler.

Ne **pas** l'utiliser pour une version défectueuse : un retour arrière suffit ([deploy-failed](deploy-failed.md)).

## Symptôme

`/api/health/ready` en échec avec des erreurs PostgreSQL sur des tables absentes ou illisibles ; ou décision prise après une suppression accidentelle.

## Vérifications

1. Quelle sauvegarde ? Par défaut la dernière. Sur le serveur : `dc run --rm --no-deps -T backup latest </dev/null`. L'horodatage (UTC) est dans le nom ; les sauvegardes mensuelles sont dans `monthly/`.
2. La clé privée `age` est-elle disponible sur le Dell (`~/.lorakus/backup-age.key`) ? Sinon la reprendre dans le gestionnaire de mots de passe. **Elle ne va jamais sur le serveur.**
3. Le Dell atteint-il B2 ? À METU, partage de connexion du téléphone obligatoire ([pièges](pitfalls.md)).

## Causes probables

Sans objet : ce runbook est une procédure, appelée par les autres.

## Actions

### 1. Sur le Dell : valider puis préparer la sauvegarde

```bash
cd ~/Documents/projets/lorakus && make restore-test
```

Si le test échoue, **s'arrêter** : cette sauvegarde n'est pas restaurable, en choisir une plus ancienne.

Télécharger et déchiffrer (remplacer `NOM` par le nom affiché à l'étape 1/5 du test, ou par une sauvegarde plus ancienne) :

```bash
NOM=lorakus-AAAAMMJJTHHMMSSZ.dump.age && umask 077 && docker compose -f compose.yml -f compose.dev.yml --env-file .env run --rm --no-deps -T backup fetch "$NOM" </dev/null > /tmp/restore.age && age --decrypt --identity ~/.lorakus/backup-age.key --output /tmp/lorakus-restore.dump /tmp/restore.age && scp /tmp/lorakus-restore.dump lorakus-prod:lorakus-restore.dump && shred -u /tmp/restore.age /tmp/lorakus-restore.dump
```

Le fichier déchiffré contient toutes les données en clair : il ne reste sur le serveur que le temps de la restauration. `scp` le dépose dans le dossier personnel du compte de l'alias `lorakus-prod` : si ce n'est pas `deploy`, le déplacer (`sudo mv … /home/deploy/ && sudo chown deploy: /home/deploy/lorakus-restore.dump`).

### 2. Sur le serveur : arrêter l'API et mettre l'état actuel à l'abri

```bash
dc stop api && /opt/lorakus/app/infra/deploy/deploy.sh backup
```

Cette sauvegarde de l'état abîmé permet de revenir en arrière. Si elle échoue parce que la base ne répond plus, continuer : il n'y a plus rien à sauver.

### 3. Restaurer

```bash
dc up -d --wait postgres && dc exec -T postgres psql -v ON_ERROR_STOP=1 -U lorakus_admin -d lorakus -c 'DROP SCHEMA IF EXISTS lorakus CASCADE' </dev/null && dc exec -T postgres pg_restore -U lorakus_admin -d lorakus --single-transaction --exit-on-error < ~/lorakus-restore.dump && echo "RESTAURATION TERMINEE"
```

- Le schéma `lorakus` contient tout (tables, extension pgvector) : il est supprimé puis recréé par la sauvegarde, avec ses propriétaires et ses droits.
- `--single-transaction` : la restauration réussit entièrement ou n'écrit rien. En cas d'échec, corriger et relancer la même commande.
- Ne pas utiliser `pg_restore --clean` : il échoue à mi-chemin dès qu'une table a été créée après la sauvegarde (constaté en test).
- C'est le seul `dc exec` qui lit volontairement l'entrée standard (le fichier de sauvegarde).

### 4. Remettre en service

```bash
dc run --rm -T migrate </dev/null && dc up -d --wait api && curl -fsS http://127.0.0.1:8001/api/health/ready && shred -u ~/lorakus-restore.dump
```

Les migrations ramènent le schéma restauré au niveau attendu par la version en service.

### Volume PostgreSQL perdu ou serveur neuf

Même procédure. `dc up -d --wait postgres` recrée d'abord une base vide avec les rôles (mots de passe de `/opt/lorakus/.env`), puis l'étape 3 s'applique telle quelle. Sur un serveur neuf, suivre avant cela `DEPLOYMENT.md` §2 et §4.1.

## Retour arrière

Restaurer de la même façon la sauvegarde faite à l'étape 2 (la plus récente dans `daily/`).

## Après la restauration

- Vérifier dans l'application que les données attendues sont là ; noter l'horodatage de la sauvegarde utilisée et la fenêtre de données perdue.
- `/opt/lorakus/app/infra/deploy/deploy.sh backup` pour repartir d'une sauvegarde saine.
- Note d'incident dans `docs/incidents/`.

## Ce qui a été vérifié

- 2026-11-10 : l'étape 3 (suppression du schéma, `pg_restore` en une transaction) a été rejouée sur un PostgreSQL 16 avec pgvector et les rôles de `infra/postgres/init/01-roles.sh`, dans deux cas : base vivante modifiée après la sauvegarde, et base neuve. Données, propriétaire du schéma, extension, droits de `lorakus_app` et privilèges par défaut retrouvés ; restauration rejouable deux fois de suite.
- **Pas encore vérifié** : la procédure complète sur PostgreSQL 18 avec les conteneurs réels. À répéter sur le staging dès qu'il existe, puis une fois par trimestre.
