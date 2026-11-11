#!/usr/bin/env bash
# Staging ephemere (ADR 0037) : rejoue sur une machine jetable, avec le vrai deploy.sh, tout ce
# que la production va vivre. Lance par deploy.yml avant la production, sur un runner ARM.
#
#   1. installe la version precedente (celle de la production), puis y ecrit une donnee temoin ;
#   2. deploie la nouvelle version par-dessus (sauvegarde avant migration, migrations, sante) ;
#   3. retour arriere, puis redeploiement de la nouvelle version ;
#   4. sauvegarde quotidienne et alerte de test ;
#   5. restauration de la derniere sauvegarde selon docs/runbooks/restore.md, donnee temoin verifiee.
#
# Variables attendues : PREV_COMMIT, PREV_API_DIGEST, PREV_BACKUP_DIGEST,
#                       NEW_COMMIT, NEW_API_DIGEST, NEW_BACKUP_DIGEST.
# Donnees synthetiques uniquement ; B2 est remplace par un dossier local, Discord par une adresse
# inerte. Aucun secret de production n'est utilise.
set -euo pipefail

for var in PREV_COMMIT PREV_API_DIGEST PREV_BACKUP_DIGEST NEW_COMMIT NEW_API_DIGEST NEW_BACKUP_DIGEST; do
  [ -n "${!var:-}" ] || { echo "Variable manquante : $var" >&2; exit 2; }
done

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${STAGING_WORK:-$(mktemp -d)}"
export LORAKUS_ROOT="$WORK/lorakus"
DEPLOY="$LORAKUS_ROOT/app/infra/deploy/deploy.sh"
READY_URL=http://127.0.0.1:8001/api/health/ready
FAKE_B2="$WORK/fake-b2"
AGE_KEY="$WORK/age.key"

step() {
  echo
  echo "################ $*"
}

fail() {
  echo "STAGING EN ECHEC : $*" >&2
  exit 1
}

# docker compose de la version en service. On utilise le deploy.sh du commit TESTE (et non
# celui de la copie, qui change de version au fil des etapes) : il connait toujours "compose".
dc() {
  "$REPO/infra/deploy/deploy.sh" compose "$@"
}

release_commit() {
  sed -n 's/^LORAKUS_RELEASE_COMMIT=//p' "$LORAKUS_ROOT/release.env"
}

expect_release() {
  local got
  got=$(release_commit)
  [ "$got" = "$1" ] || fail "version en service $got, attendue $1"
  curl -fsS --max-time 5 "$READY_URL" >/dev/null || fail "/api/health/ready ne repond pas"
  echo "OK : version $1 en service et saine"
}

backups() {
  find "$FAKE_B2/daily" -name 'lorakus-*.dump.age' 2>/dev/null | sort
}

marker() {
  dc exec -T postgres psql -U lorakus_admin -d lorakus -qtA \
    -c "select note from lorakus.staging_marker order by id" </dev/null
}

on_exit() {
  local status=$?
  if [ "$status" -ne 0 ] && [ -f "$LORAKUS_ROOT/release.env" ]; then
    echo "---- etat des services"
    dc ps -a || true
    echo "---- journaux (fin)"
    dc logs --tail 40 api migrate postgres backup || true
  fi
  exit "$status"
}
trap on_exit EXIT

step "Preparation de l'hote jetable"
mkdir -p "$LORAKUS_ROOT" "$FAKE_B2"
# Le conteneur de sauvegarde (utilisateur postgres) doit pouvoir ecrire dans le faux B2.
chmod 777 "$FAKE_B2"
# Depot "origin" local dont main est le commit a deployer : deploy.sh verifie l'appartenance a main.
git init --quiet --bare "$WORK/origin.git"
git -C "$REPO" push --quiet "$WORK/origin.git" "$NEW_COMMIT:refs/heads/main"
git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
git clone --quiet "$WORK/origin.git" "$LORAKUS_ROOT/app"
git -C "$LORAKUS_ROOT/app" checkout --quiet --detach "$PREV_COMMIT"
cp "$REPO/infra/staging/compose.staging.yml" "$LORAKUS_ROOT/compose.host.yml"

age-keygen -o "$AGE_KEY" 2>/dev/null
random_hex() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
umask 077
cat > "$LORAKUS_ROOT/.env" <<ENV
LORAKUS_ENVIRONMENT=staging
POSTGRES_DB=lorakus
POSTGRES_USER=lorakus_admin
POSTGRES_PASSWORD=$(random_hex)
LORAKUS_MIGRATOR_DB_PASSWORD=$(random_hex)
LORAKUS_APP_DB_PASSWORD=$(random_hex)
GRAFANA_ADMIN_PASSWORD=$(random_hex)
DISCORD_OPS_WEBHOOK_URL=http://127.0.0.1:9/staging-sans-discord
HEALTHCHECKS_PING_URL=http://127.0.0.1:9/staging-sans-sentinelle
B2_KEY_ID=staging
B2_APP_KEY=staging
B2_BUCKET=/fake-b2
BACKUP_AGE_RECIPIENT=$(age-keygen -y "$AGE_KEY")
STAGING_FAKE_B2_DIR=$FAKE_B2
ENV
umask 022

step "1/6 Installation de la version de production ($PREV_COMMIT)"
"$DEPLOY" deploy "$PREV_COMMIT" "$PREV_API_DIGEST" "$PREV_BACKUP_DIGEST"
expect_release "$PREV_COMMIT"
dc exec -T postgres psql -v ON_ERROR_STOP=1 -U lorakus_migrator -d lorakus -q \
  -c "create table lorakus.staging_marker (id serial primary key, note text not null);
      insert into lorakus.staging_marker (note) values ('ecrite-avant-la-mise-a-jour');" </dev/null
[ "$(marker)" = "ecrite-avant-la-mise-a-jour" ] || fail "donnee temoin non ecrite"

step "2/6 Mise a jour vers la nouvelle version ($NEW_COMMIT)"
"$DEPLOY" deploy "$NEW_COMMIT" "$NEW_API_DIGEST" "$NEW_BACKUP_DIGEST"
expect_release "$NEW_COMMIT"
[ "$(backups | wc -l)" -ge 1 ] || fail "aucune sauvegarde avant migration"
[ "$(marker)" = "ecrite-avant-la-mise-a-jour" ] || fail "donnee temoin perdue pendant la mise a jour"

step "3/6 Retour arriere puis redeploiement"
"$DEPLOY" rollback
expect_release "$PREV_COMMIT"
"$DEPLOY" deploy "$NEW_COMMIT" "$NEW_API_DIGEST" "$NEW_BACKUP_DIGEST"
expect_release "$NEW_COMMIT"

step "4/6 Sauvegarde quotidienne et alerte de test"
before=$(backups | wc -l)
# Les noms de sauvegarde sont a la seconde pres.
sleep 1
"$DEPLOY" backup
[ "$(backups | wc -l)" -gt "$before" ] || fail "la sauvegarde quotidienne n'a rien produit"
dc exec -T node-exporter cat /textfile/lorakus_backup.prom </dev/null | grep -qx 'lorakus_backup_last_success 1' \
  || fail "metrique de sauvegarde absente ou en echec"
"$DEPLOY" alert-test

step "5/6 Restauration (docs/runbooks/restore.md)"
dc exec -T postgres psql -v ON_ERROR_STOP=1 -U lorakus_admin -d lorakus -q \
  -c "insert into lorakus.staging_marker (note) values ('ecrite-apres-la-sauvegarde')" </dev/null
latest=$(backups | tail -n 1)
age --decrypt --identity "$AGE_KEY" --output "$WORK/restore.dump" "$latest"
dc stop api
dc exec -T postgres psql -v ON_ERROR_STOP=1 -U lorakus_admin -d lorakus \
  -c 'DROP SCHEMA IF EXISTS lorakus CASCADE' </dev/null
dc exec -T postgres pg_restore -U lorakus_admin -d lorakus --single-transaction --exit-on-error < "$WORK/restore.dump"
dc run --rm -T migrate </dev/null
dc up -d --wait api
expect_release "$NEW_COMMIT"
[ "$(marker)" = "ecrite-avant-la-mise-a-jour" ] \
  || fail "apres restauration, la base ne contient pas exactement l'etat sauvegarde : $(marker | tr '\n' ' ')"
[ "$(dc exec -T postgres psql -U lorakus_app -d lorakus -qtA -c 'select count(*) from lorakus.staging_marker' </dev/null)" = "1" ] \
  || fail "lorakus_app ne lit plus les donnees restaurees"

step "6/6 Termine"
echo "Staging reussi : mise a jour, retour arriere, sauvegarde et restauration verifies."
