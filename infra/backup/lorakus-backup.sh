#!/usr/bin/env bash
# Sauvegarde chiffree de PostgreSQL vers Backblaze B2, et utilitaires de restauration.
#   lorakus-backup backup      pg_dump -> chiffrement age (cle PUBLIQUE) -> b2:<bucket>/daily/
#                              puis ecriture des metriques lues par node_exporter
#   lorakus-backup latest      nom de la derniere sauvegarde quotidienne
#   lorakus-backup fetch NOM   contenu CHIFFRE de NOM sur la sortie standard
# Ce conteneur ne detient jamais la cle privee : il peut chiffrer, jamais dechiffrer.
set -euo pipefail

: "${B2_BUCKET:?B2_BUCKET manquant}"
REMOTE="b2:${B2_BUCKET}"
NAME_PATTERN='^lorakus-[0-9]{8}T[0-9]{6}Z\.dump\.age$'
METRICS_DIR="${BACKUP_METRICS_DIR:-/metrics}"
METRICS_FILE="$METRICS_DIR/lorakus_backup.prom"
SIZE_FILE=/tmp/lorakus-backup-size
WORK=""
trap 'if [ -n "$WORK" ]; then rm -rf "$WORK"; fi' EXIT

# Valeur precedente d'une metrique dans le fichier (vide si absente).
previous_value() {
  if [ -f "$METRICS_FILE" ]; then
    sed -n "s/^$1 //p" "$METRICS_FILE"
  fi
}

# Ecrit les metriques lues par node_exporter (collecteur "textfile").
# Ecriture atomique : fichier temporaire puis renommage, jamais de fichier a moitie ecrit.
write_metrics() {
  local status="$1" size="$2" now last_success tmp
  if [ ! -d "$METRICS_DIR" ] || [ ! -w "$METRICS_DIR" ]; then
    echo "Metriques non ecrites : $METRICS_DIR absent ou non inscriptible" >&2
    return 0
  fi
  now=$(date -u +%s)
  last_success=$(previous_value lorakus_backup_last_success_timestamp_seconds)
  if [ "$status" = "1" ]; then
    last_success="$now"
  else
    size=$(previous_value lorakus_backup_size_bytes)
  fi
  tmp=$(mktemp "$METRICS_DIR/.lorakus_backup.XXXXXX")
  {
    echo "# HELP lorakus_backup_last_attempt_timestamp_seconds Date de la derniere tentative de sauvegarde."
    echo "# TYPE lorakus_backup_last_attempt_timestamp_seconds gauge"
    echo "lorakus_backup_last_attempt_timestamp_seconds $now"
    echo "# HELP lorakus_backup_last_success Resultat de la derniere tentative (1 = reussie, 0 = echec)."
    echo "# TYPE lorakus_backup_last_success gauge"
    echo "lorakus_backup_last_success $status"
    if [ -n "$last_success" ]; then
      echo "# HELP lorakus_backup_last_success_timestamp_seconds Date de la derniere sauvegarde reussie."
      echo "# TYPE lorakus_backup_last_success_timestamp_seconds gauge"
      echo "lorakus_backup_last_success_timestamp_seconds $last_success"
    fi
    if [ -n "$size" ]; then
      echo "# HELP lorakus_backup_size_bytes Taille de la derniere sauvegarde chiffree reussie."
      echo "# TYPE lorakus_backup_size_bytes gauge"
      echo "lorakus_backup_size_bytes $size"
    fi
  } > "$tmp"
  chmod 0644 "$tmp"
  mv "$tmp" "$METRICS_FILE"
}

run_backup() {
  : "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT manquant}"
  local name
  name="lorakus-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
  WORK=$(mktemp -d /tmp/backup.XXXXXX)

  # Dump chiffre a la volee : la version en clair ne touche jamais le disque.
  # --enable-row-security : avec la RLS forcee (PR 23), pg_dump refuse sinon de lire les
  # tables, meme en proprietaire. La politique de lorakus_migrator lui laisse tout lire.
  pg_dump --format=custom --enable-row-security | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$WORK/$name"

  rclone copyto "$WORK/$name" "$REMOTE/daily/$name" --retries 3
  # Le 1er du mois, une copie est aussi conservee 12 mois (regle du bucket monthly/).
  if [ "$(date -u +%d)" = "01" ]; then
    rclone copyto "$REMOTE/daily/$name" "$REMOTE/monthly/$name" --retries 3
  fi
  stat -c %s "$WORK/$name" > "$SIZE_FILE"
  echo "Sauvegarde envoyee : daily/$name ($(cat "$SIZE_FILE") octets chiffres)"
}

backup() {
  local status=0
  # La sauvegarde s'execute dans un processus separe : "set -e" y reste pleinement
  # actif (bash l'ignore dans une fonction appelee depuis un "if" ou un "||").
  "$0" _run || status=$?
  if [ "$status" -eq 0 ]; then
    write_metrics 1 "$(cat "$SIZE_FILE")"
  else
    echo "ECHEC de la sauvegarde (code $status)" >&2
    write_metrics 0 ""
  fi
  return "$status"
}

latest() {
  rclone lsf "$REMOTE/daily/" --files-only | { grep -E "$NAME_PATTERN" || true; } | sort | tail -n 1
}

fetch() {
  local name="${1:-}"
  # Nom strictement controle : aucun chemin arbitraire ne peut etre lu.
  [[ "$name" =~ $NAME_PATTERN ]] || { echo "Nom de sauvegarde invalide : $name" >&2; exit 2; }
  rclone cat "$REMOTE/daily/$name"
}

case "${1:-backup}" in
  backup) backup ;;
  _run) run_backup ;;
  latest) latest ;;
  fetch) fetch "${2:-}" ;;
  *) echo "Usage : lorakus-backup [backup|latest|fetch NOM]" >&2; exit 2 ;;
esac
