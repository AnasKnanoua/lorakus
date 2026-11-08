#!/usr/bin/env bash
# Verifie que les roles PostgreSQL respectent le moindre privilege.
# Usage : make db-check
set -euo pipefail
cd "$(dirname "$0")/../.."

set -a; source .env; set +a
COMPOSE=(docker compose -f compose.yml -f compose.dev.yml --env-file .env)

# Execute une requete en tant que $1 (mot de passe $2), via TCP avec authentification.
psql_as() {
  "${COMPOSE[@]}" exec -T -e PGPASSWORD="$2" postgres \
    psql -h localhost -U "$1" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -qtA -c "$3"
}

passed=0
failed=0
ok() { echo "  OK     $1"; passed=$((passed + 1)); }
ko() { echo "  ECHEC  $1"; failed=$((failed + 1)); }

APP=(lorakus_app "$LORAKUS_APP_DB_PASSWORD")
MIG=(lorakus_migrator "$LORAKUS_MIGRATOR_DB_PASSWORD")

echo "Verification des roles PostgreSQL"

[ "$(psql_as "${APP[@]}" "select 1")" = "1" ] \
  && ok "lorakus_app se connecte avec son mot de passe" \
  || ko "lorakus_app se connecte avec son mot de passe"

[ "$(psql_as "${APP[@]}" "select rolsuper::text from pg_roles where rolname = current_user")" = "false" ] \
  && ok "lorakus_app n'est pas superutilisateur" \
  || ko "lorakus_app n'est pas superutilisateur"

if psql_as "${APP[@]}" "create table interdit (id int)" >/dev/null 2>&1; then
  ko "lorakus_app ne peut pas creer de table"
else
  ok "lorakus_app ne peut pas creer de table"
fi

if psql_as "${APP[@]}" "create table public.interdit (id int)" >/dev/null 2>&1; then
  ko "le schema public est ferme"
else
  ok "le schema public est ferme"
fi

if psql_as "${MIG[@]}" "create table verif_tmp (id int)" >/dev/null; then
  ok "lorakus_migrator peut creer une table"
  [ "$(psql_as "${APP[@]}" "insert into verif_tmp values (1); select count(*) from verif_tmp")" = "1" ] \
    && ok "lorakus_app lit et ecrit les donnees des nouvelles tables" \
    || ko "lorakus_app lit et ecrit les donnees des nouvelles tables"
  if psql_as "${APP[@]}" "drop table verif_tmp" >/dev/null 2>&1; then
    ko "lorakus_app ne peut pas supprimer une table"
  else
    ok "lorakus_app ne peut pas supprimer une table"
  fi
  psql_as "${MIG[@]}" "drop table verif_tmp" >/dev/null
else
  ko "lorakus_migrator peut creer une table"
fi

[ "$(psql_as "${APP[@]}" "select extname from pg_extension where extname = 'vector'")" = "vector" ] \
  && ok "extension pgvector installee" \
  || ko "extension pgvector installee"

echo "Resultat : $passed reussi(s), $failed echec(s)"
[ "$failed" -eq 0 ]
