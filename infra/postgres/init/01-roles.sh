#!/usr/bin/env bash
# Execute UNE SEULE FOIS par l'image PostgreSQL, a la creation du volume.
# Cree les roles a moindre privilege et le schema de l'application.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v migrator_pw="$LORAKUS_MIGRATOR_DB_PASSWORD" \
  -v app_pw="$LORAKUS_APP_DB_PASSWORD" \
  -v db="$POSTGRES_DB" <<'EOSQL'

-- Proprietaire du schema : utilise uniquement par les migrations.
CREATE ROLE lorakus_migrator LOGIN PASSWORD :'migrator_pw';

-- Role de l'application : donnees seulement, jamais la structure, jamais de contournement RLS.
CREATE ROLE lorakus_app LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- Personne d'autre ne peut se connecter a la base.
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO lorakus_migrator, lorakus_app;

-- Le schema "public" est ferme ; tout vit dans le schema "lorakus".
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA lorakus AUTHORIZATION lorakus_migrator;
GRANT USAGE ON SCHEMA lorakus TO lorakus_app;

-- pgvector (embeddings de la memoire, phase 3).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA lorakus;

ALTER ROLE lorakus_migrator SET search_path = lorakus;
ALTER ROLE lorakus_app SET search_path = lorakus;

-- Toute table creee plus tard par les migrations sera automatiquement
-- lisible et modifiable (donnees uniquement) par l'application.
ALTER DEFAULT PRIVILEGES FOR ROLE lorakus_migrator IN SCHEMA lorakus
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lorakus_app;
ALTER DEFAULT PRIVILEGES FOR ROLE lorakus_migrator IN SCHEMA lorakus
  GRANT USAGE, SELECT ON SEQUENCES TO lorakus_app;
EOSQL
