#!/usr/bin/env bash
# Test de restauration, execute sur le poste de developpement (seul lieu ou se trouve la cle privee) :
# la derniere sauvegarde quotidienne est telechargee depuis B2, dechiffree, restauree dans une
# base PostgreSQL jetable SANS acces reseau, puis verifiee.
set -euo pipefail
cd "$(dirname "$0")/../.."

AGE_KEY="${BACKUP_AGE_KEY_FILE:-$HOME/.lorakus/backup-age.key}"
[ -r "$AGE_KEY" ] || { echo "Cle privee introuvable : $AGE_KEY" >&2; exit 1; }

COMPOSE=(docker compose -f compose.yml -f compose.dev.yml --env-file .env)
PG_IMAGE=$("${COMPOSE[@]}" config --images | grep -m1 pgvector)
CONTAINER=lorakus-restore-test
WORK=$(mktemp -d)
chmod 700 "$WORK"
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

passed=0
failed=0
check() {
  if [ "$2" = "$3" ]; then
    echo "  OK     $1"
    passed=$((passed + 1))
  else
    echo "  ECHEC  $1 (obtenu : '$2', attendu : '$3')"
    failed=$((failed + 1))
  fi
}

echo "1/5 Recherche de la derniere sauvegarde"
LATEST=$("${COMPOSE[@]}" run --rm --no-deps -T backup latest)
[ -n "$LATEST" ] || { echo "Aucune sauvegarde dans daily/" >&2; exit 1; }
echo "    $LATEST"

echo "2/5 Telechargement puis dechiffrement (cle privee locale)"
"${COMPOSE[@]}" run --rm --no-deps -T backup fetch "$LATEST" > "$WORK/backup.age"
age --decrypt --identity "$AGE_KEY" --output "$WORK/backup.dump" "$WORK/backup.age"

echo "3/5 Demarrage d'une base jetable, sans aucun acces reseau"
docker run -d --name "$CONTAINER" --network none \
  -e POSTGRES_DB=lorakus -e POSTGRES_USER=restore_admin \
  -e POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  "$PG_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  # Journaux lus d'abord : « ... | grep -q » echoue au hasard avec pipefail (pitfalls.md).
  if grep -qF "PostgreSQL init process complete" <<<"$(docker logs "$CONTAINER" 2>&1)" \
     && docker exec "$CONTAINER" pg_isready -U restore_admin -d lorakus >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" pg_isready -U restore_admin -d lorakus >/dev/null

echo "4/5 Restauration"
docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -q -U restore_admin -d lorakus \
  -c "CREATE ROLE lorakus_migrator NOLOGIN; CREATE ROLE lorakus_app NOLOGIN;"
docker exec -i "$CONTAINER" pg_restore -U restore_admin -d lorakus --exit-on-error < "$WORK/backup.dump"

echo "5/5 Verifications"
q() { docker exec "$CONTAINER" psql -U restore_admin -d lorakus -qtA -c "$1"; }
check "version du schema presente" "$(q 'select count(*) from lorakus.alembic_version')" "1"
check "extension pgvector restauree" "$(q "select extname from pg_extension where extname = 'vector'")" "vector"
check "schema lorakus appartient au migrateur" "$(q "select nspowner::regrole from pg_namespace where nspname = 'lorakus'")" "lorakus_migrator"

ts=${LATEST#lorakus-}
ts=${ts%.dump.age}
backup_epoch=$(date -u -d "${ts:0:4}-${ts:4:2}-${ts:6:2} ${ts:9:2}:${ts:11:2}:${ts:13:2}" +%s)
age_hours=$(( ($(date -u +%s) - backup_epoch) / 3600 ))
check "sauvegarde de moins de 26 h (${age_hours} h)" "$([ "$age_hours" -lt 26 ] && echo oui || echo non)" "oui"
echo "    tables restaurees dans lorakus : $(q "select count(*) from pg_tables where schemaname = 'lorakus'")"

echo "Resultat : $passed reussi(s), $failed echec(s)"
[ "$failed" -eq 0 ]
