#!/usr/bin/env bash
# Cree ou complete le fichier des secrets de production, SUR le serveur.
#   init-env.sh [FICHIER]      (par defaut : /opt/lorakus/.env)
# - Les mots de passe internes sont tires au hasard ici meme : ils ne quittent jamais le serveur.
# - Les valeurs venant de services externes (Discord, Backblaze B2, age) sont demandees au clavier.
# - Une valeur deja presente n'est JAMAIS modifiee : relancer le script est sans danger, et
#   PostgreSQL garde les mots de passe choisis a la creation de la base.
set -euo pipefail

ENV_FILE="${1:-/opt/lorakus/.env}"

# Le fichier n'est lisible que par son proprietaire (droits 600).
umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

has() {
  grep -q "^$1=." "$ENV_FILE"
}

put() {
  # Retire une eventuelle ligne vide pour cette cle, puis ajoute la valeur.
  local tmp
  tmp=$(mktemp "$ENV_FILE.XXXXXX")
  grep -v "^$1=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# 48 caracteres hexadecimaux tires du generateur aleatoire du noyau.
random_hex() {
  head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

fixed() {
  if has "$1"; then
    echo "  conserve   $1"
  else
    put "$1" "$2"
    echo "  ajoute     $1"
  fi
}

generated() {
  if has "$1"; then
    echo "  conserve   $1"
  else
    put "$1" "$(random_hex)"
    echo "  genere     $1"
  fi
}

# asked CLE "question" MOTIF secret|visible
asked() {
  local key="$1" question="$2" pattern="$3" mode="$4" value
  if has "$key"; then
    echo "  conserve   $key"
    return 0
  fi
  while true; do
    if [ "$mode" = "secret" ]; then
      # -s : la saisie ne s'affiche pas a l'ecran.
      read -r -s -p "$question : " value
      echo
    else
      read -r -p "$question : " value
    fi
    if [[ "$value" =~ $pattern ]]; then
      break
    fi
    echo "  Valeur refusee (format inattendu), recommence." >&2
  done
  put "$key" "$value"
  echo "  enregistre $key"
}

echo "Fichier : $ENV_FILE"

fixed LORAKUS_ENVIRONMENT production
fixed POSTGRES_DB lorakus
fixed POSTGRES_USER lorakus_admin
generated POSTGRES_PASSWORD
generated LORAKUS_MIGRATOR_DB_PASSWORD
generated LORAKUS_APP_DB_PASSWORD
generated GRAFANA_ADMIN_PASSWORD

asked DISCORD_OPS_WEBHOOK_URL "URL du webhook Discord (#lorakus-infra)" '^https://(discord|discordapp)\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+$' secret
asked B2_KEY_ID "Identifiant de la cle B2 (keyID)" '^[A-Za-z0-9]+$' visible
asked B2_APP_KEY "Cle d'application B2 (applicationKey)" '^[A-Za-z0-9/+_-]+$' secret
asked B2_BUCKET "Nom du bucket B2" '^[a-z0-9][a-z0-9-]+$' visible
asked BACKUP_AGE_RECIPIENT "Cle PUBLIQUE age (commence par age1)" '^age1[a-z0-9]+$' visible

chmod 600 "$ENV_FILE"
echo "Termine. Aucun secret n'a ete affiche."
