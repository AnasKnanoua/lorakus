#!/usr/bin/env bash
# Sauvegarde chiffree de PostgreSQL vers Backblaze B2, et utilitaires de restauration.
#   lorakus-backup backup      pg_dump -> chiffrement age (cle PUBLIQUE) -> b2:<bucket>/daily/
#   lorakus-backup latest      nom de la derniere sauvegarde quotidienne
#   lorakus-backup fetch NOM   contenu CHIFFRE de NOM sur la sortie standard
# Ce conteneur ne detient jamais la cle privee : il peut chiffrer, jamais dechiffrer.
set -euo pipefail

: "${B2_BUCKET:?B2_BUCKET manquant}"
REMOTE="b2:${B2_BUCKET}"
NAME_PATTERN='^lorakus-[0-9]{8}T[0-9]{6}Z\.dump\.age$'
WORK=""
trap 'if [ -n "$WORK" ]; then rm -rf "$WORK"; fi' EXIT

backup() {
  : "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT manquant}"
  local name
  name="lorakus-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
  WORK=$(mktemp -d /tmp/backup.XXXXXX)

  # Dump chiffre a la volee : la version en clair ne touche jamais le disque.
  pg_dump --format=custom | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$WORK/$name"

  rclone copyto "$WORK/$name" "$REMOTE/daily/$name" --retries 3
  # Le 1er du mois, une copie est aussi conservee 12 mois (regle du bucket monthly/).
  if [ "$(date -u +%d)" = "01" ]; then
    rclone copyto "$REMOTE/daily/$name" "$REMOTE/monthly/$name" --retries 3
  fi
  echo "Sauvegarde envoyee : daily/$name ($(stat -c %s "$WORK/$name") octets chiffres)"
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
  latest) latest ;;
  fetch) fetch "${2:-}" ;;
  *) echo "Usage : lorakus-backup [backup|latest|fetch NOM]" >&2; exit 2 ;;
esac
