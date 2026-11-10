#!/usr/bin/env bash
# Deploiement de Lorakus. S'execute SUR le serveur, avec l'utilisateur deploy.
#
#   deploy.sh deploy COMMIT EMPREINTE_API EMPREINTE_SAUVEGARDE   met en service une version
#   deploy.sh rollback                                           revient a la version precedente
#   deploy.sh status                                             affiche la version en service
#   deploy.sh backup                                             sauvegarde (minuteur systemd quotidien)
#   deploy.sh ssh                                                point d'entree de la cle de GitHub
#
# COMMIT : commit de la branche main (40 caracteres). Il fixe la CONFIGURATION (fichiers Compose,
#          Prometheus, Grafana...), recuperee depuis le depot public.
# EMPREINTE : sha256 de l'image publiee sur GHCR. Elle fixe le CODE execute.
#
# Deroulement d'un deploiement : sauvegarde de la base -> migrations -> demarrage -> test de
# /api/health/ready. Si une etape echoue, la version precedente est remise en service.
set -euo pipefail

# Fichiers lisibles par les conteneurs (configuration montee en lecture seule).
umask 022

ROOT="${LORAKUS_ROOT:-/opt/lorakus}"
APP="$ROOT/app"                        # copie du depot, positionnee sur le commit deploye
ENV_FILE="$ROOT/.env"                  # secrets, crees par init-env.sh
RELEASE="$ROOT/release.env"            # version en service
PREVIOUS="$ROOT/release.previous.env"  # version precedente (pour rollback)
NEXT="$ROOT/release.next.env"          # version en cours de deploiement
LOCK="$ROOT/deploy.lock"
REGISTRY="${LORAKUS_REGISTRY:-ghcr.io/anasknanoua}"
READY_URL="${LORAKUS_READY_URL:-http://127.0.0.1:8001/api/health/ready}"

say() {
  echo "==> $*"
}

fail() {
  echo "ECHEC : $*" >&2
  exit 1
}

# docker compose avec tous les fichiers de la production. $1 = fichier de version a utiliser.
compose() {
  local release_file="$1"
  shift
  docker compose --project-directory "$APP" \
    -f "$APP/compose.yml" -f "$APP/compose.observability.yml" -f "$APP/compose.prod.yml" \
    --env-file "$ENV_FILE" --env-file "$release_file" "$@"
}

# Une seule operation a la fois (deploiement, retour arriere, sauvegarde).
# Le verrou reste tenu quand le script se relance lui-meme.
# $1 (facultatif) : secondes d'attente si le verrou est pris ; sans valeur, refus immediat.
take_lock() {
  local wait="${1:-}"
  if [ "${LORAKUS_DEPLOY_LOCKED:-}" = "1" ]; then
    return 0
  fi
  exec 9>"$LOCK"
  if [ -n "$wait" ]; then
    flock -w "$wait" 9 || fail "verrou toujours pris apres $wait s (deploiement bloque ?)"
  else
    flock -n 9 || fail "un autre deploiement est deja en cours"
  fi
  export LORAKUS_DEPLOY_LOCKED=1
}

# Place la copie du depot sur un commit, apres avoir verifie qu'il appartient bien a main.
checkout_commit() {
  local commit="$1"
  git -C "$APP" fetch --quiet origin main
  git -C "$APP" merge-base --is-ancestor "$commit" origin/main \
    || fail "le commit $commit n'appartient pas a la branche main"
  git -C "$APP" checkout --quiet --force --detach "$commit"
}

release_value() {
  sed -n "s/^$2=//p" "$1"
}

write_release() {
  local file="$1" commit="$2" api="$3" backup="$4" tmp
  tmp=$(mktemp "$file.XXXXXX")
  {
    echo "LORAKUS_RELEASE_COMMIT=$commit"
    echo "LORAKUS_API_IMAGE=$api"
    echo "LORAKUS_BACKUP_IMAGE=$backup"
    echo "LORAKUS_RELEASED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$tmp"
  chmod 644 "$tmp"
  mv "$tmp" "$file"
}

same_release() {
  [ -f "$1" ] && [ -f "$2" ] \
    && [ "$(release_value "$1" LORAKUS_RELEASE_COMMIT)" = "$(release_value "$2" LORAKUS_RELEASE_COMMIT)" ] \
    && [ "$(release_value "$1" LORAKUS_API_IMAGE)" = "$(release_value "$2" LORAKUS_API_IMAGE)" ] \
    && [ "$(release_value "$1" LORAKUS_BACKUP_IMAGE)" = "$(release_value "$2" LORAKUS_BACKUP_IMAGE)" ]
}

wait_ready() {
  local attempt
  for attempt in $(seq 1 15); do
    if curl -fsS --max-time 5 -o /dev/null "$READY_URL"; then
      say "API prete (essai $attempt)"
      return 0
    fi
    sleep 2
  done
  return 1
}

# Les services d'observabilite lisent leur configuration (fichiers du depot montes en lecture
# seule) au demarrage seulement : docker compose ne les recree pas quand seuls ces fichiers
# changent. On les recree donc a chaque mise en service (leurs donnees restent dans les volumes).
OBSERVABILITY_SERVICES=(prometheus alertmanager grafana)

start_services() {
  local release_file="$1"
  compose "$release_file" up -d --wait --remove-orphans || return 1
  compose "$release_file" up -d --wait --no-deps --force-recreate "${OBSERVABILITY_SERVICES[@]}" || return 1
}

# Met une version en service. Renvoie 1 a la premiere etape en echec (rien n'est masque).
activate() {
  local mode="$1" release_file="$2"
  if [ "$mode" = "deploy" ]; then
    say "Demarrage de PostgreSQL"
    compose "$release_file" up -d --wait postgres || return 1
    say "Migrations"
    compose "$release_file" run --rm -T migrate </dev/null || return 1
  fi
  say "Demarrage des services"
  start_services "$release_file" || return 1
  say "Test de $READY_URL"
  wait_ready || return 1
}

# Remet en service la version enregistree dans release.env.
restore_current() {
  local commit
  commit=$(release_value "$RELEASE" LORAKUS_RELEASE_COMMIT)
  git -C "$APP" checkout --quiet --force --detach "$commit" || return 1
  start_services "$RELEASE" || return 1
  wait_ready || return 1
}

cmd_deploy() {
  local commit="${1:-}" api_digest="${2:-}" backup_digest="${3:-}"
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || fail "commit invalide (40 caracteres hexadecimaux attendus)"
  [[ "$api_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "empreinte de l'image API invalide"
  [[ "$backup_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "empreinte de l'image de sauvegarde invalide"
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE absent : lancer d'abord infra/deploy/init-env.sh"

  take_lock
  say "Configuration : commit $commit"
  checkout_commit "$commit"
  # On relance le script tel qu'il existe dans le commit deploye.
  exec "$APP/infra/deploy/deploy.sh" apply deploy "$commit" \
    "$REGISTRY/lorakus-api@$api_digest" "$REGISTRY/lorakus-backup@$backup_digest"
}

cmd_rollback() {
  [ -f "$PREVIOUS" ] || fail "aucune version precedente enregistree"
  local commit api backup
  commit=$(release_value "$PREVIOUS" LORAKUS_RELEASE_COMMIT)
  api=$(release_value "$PREVIOUS" LORAKUS_API_IMAGE)
  backup=$(release_value "$PREVIOUS" LORAKUS_BACKUP_IMAGE)

  take_lock
  say "Retour a la version precedente : commit $commit"
  checkout_commit "$commit"
  exec "$APP/infra/deploy/deploy.sh" apply rollback "$commit" "$api" "$backup"
}

# Etape interne, lancee par deploy et rollback une fois la configuration en place.
cmd_apply() {
  local mode="${1:-}" commit="${2:-}" api="${3:-}" backup="${4:-}"
  [ "${LORAKUS_DEPLOY_LOCKED:-}" = "1" ] || fail "apply est une etape interne : utiliser deploy ou rollback"
  [ "$mode" = "deploy" ] || [ "$mode" = "rollback" ] || fail "mode inconnu : $mode"

  write_release "$NEXT" "$commit" "$api" "$backup"

  say "Telechargement des images"
  if ! compose "$NEXT" --profile tools pull --quiet; then
    rm -f "$NEXT"
    fail "telechargement des images impossible (rien n'a ete modifie)"
  fi

  # Avant de toucher a la base : une sauvegarde, faite avec la version en service.
  # Elle n'a pas lieu au premier deploiement (la base n'existe pas encore).
  if [ "$mode" = "deploy" ] && [ -f "$RELEASE" ] && [ "${LORAKUS_DEPLOY_SKIP_BACKUP:-}" != "1" ]; then
    say "Sauvegarde avant migration"
    if ! compose "$RELEASE" run --rm -T backup </dev/null; then
      rm -f "$NEXT"
      fail "sauvegarde impossible : deploiement annule (rien n'a ete modifie)"
    fi
  fi

  if ! activate "$mode" "$NEXT"; then
    rm -f "$NEXT"
    if [ -f "$RELEASE" ]; then
      say "Echec : remise en service de la version en place avant ce deploiement"
      restore_current || fail "le retour automatique a aussi echoue : intervention manuelle necessaire"
      fail "la nouvelle version n'a pas demarre correctement ; la version precedente est de nouveau en service"
    fi
    fail "premier deploiement en echec : voir les journaux avec docker compose logs"
  fi

  # Succes : la version en service devient la precedente, la nouvelle devient la version en service.
  if same_release "$NEXT" "$RELEASE"; then
    rm -f "$NEXT"
  else
    if [ -f "$RELEASE" ]; then
      mv "$RELEASE" "$PREVIOUS"
    fi
    mv "$NEXT" "$RELEASE"
  fi
  say "Version en service :"
  cat "$RELEASE"
}

# Sauvegarde de la version en service. Lancee chaque nuit par le minuteur lorakus-backup.timer.
# Si un deploiement est en cours, elle attend qu'il se termine (30 minutes au plus).
cmd_backup() {
  [ -f "$RELEASE" ] || fail "aucune version deployee : rien a sauvegarder"
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE absent"
  take_lock 1800
  say "Sauvegarde de la version en service"
  # -T et </dev/null : docker compose run ne doit jamais lire l'entree standard.
  compose "$RELEASE" run --rm -T backup </dev/null
}

cmd_status() {
  if [ -f "$RELEASE" ]; then
    echo "--- en service"
    cat "$RELEASE"
  else
    echo "Aucune version deployee."
  fi
  if [ -f "$PREVIOUS" ]; then
    echo "--- precedente"
    cat "$PREVIOUS"
  fi
}

# La cle SSH confiee a GitHub est limitee a ce point d'entree (voir DEPLOYMENT.md) : elle ne peut
# pas ouvrir de terminal. La commande demandee est lue mot par mot, jamais executee telle quelle.
cmd_ssh() {
  local -a words
  read -r -a words <<< "${SSH_ORIGINAL_COMMAND:-}"
  case "${words[0]:-}" in
    deploy)
      [ "${#words[@]}" -eq 4 ] || fail "usage : deploy COMMIT EMPREINTE_API EMPREINTE_SAUVEGARDE"
      cmd_deploy "${words[1]}" "${words[2]}" "${words[3]}"
      ;;
    rollback)
      [ "${#words[@]}" -eq 1 ] || fail "usage : rollback"
      cmd_rollback
      ;;
    status)
      [ "${#words[@]}" -eq 1 ] || fail "usage : status"
      cmd_status
      ;;
    *) fail "commande refusee (autorisees : deploy, rollback, status)" ;;
  esac
}

main() {
  local command="${1:-}"
  if [ "$#" -gt 0 ]; then
    shift
  fi
  case "$command" in
    deploy) cmd_deploy "$@" ;;
    rollback) cmd_rollback ;;
    apply) cmd_apply "$@" ;;
    status) cmd_status ;;
    backup) cmd_backup ;;
    ssh) cmd_ssh ;;
    *) fail "usage : deploy.sh deploy COMMIT EMPREINTE_API EMPREINTE_SAUVEGARDE | rollback | status | backup" ;;
  esac
}

# Tout le script est lu avant d'etre execute (fonction main + exit) : il peut ainsi changer
# de version sous ses propres pieds pendant un deploiement sans se melanger les lignes.
main "$@"
exit
