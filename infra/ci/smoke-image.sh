#!/usr/bin/env bash
# Verifie qu'une image construite demarre et respecte nos regles de securite.
# A lancer sur une machine de la meme architecture que l'image (pas d'emulation).
#   smoke-image.sh api    IMAGE ARCH    demarre l'API et l'interroge
#   smoke-image.sh backup IMAGE ARCH    verifie les outils de sauvegarde
# ARCH vaut amd64 ou arm64.
set -euo pipefail

KIND="${1:?usage: smoke-image.sh api|backup IMAGE ARCH}"
IMAGE="${2:?usage: smoke-image.sh api|backup IMAGE ARCH}"
ARCH="${3:?usage: smoke-image.sh api|backup IMAGE ARCH}"

# Memes protections que dans compose.yml : si l'image ne les supporte pas, on le voit ici.
HARDENING=(--read-only --cap-drop ALL --security-opt no-new-privileges:true --tmpfs /tmp:size=16m)

# Conteneur de test en cours : quoi qu'il arrive, il est supprime a la fin.
CONTAINER=""
trap 'if [ -n "$CONTAINER" ]; then docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; fi' EXIT

fail() {
  echo "ECHEC : $*" >&2
  exit 1
}

actual_arch=$(docker image inspect -f '{{.Architecture}}' "$IMAGE")
if [ "$actual_arch" != "$ARCH" ]; then
  fail "architecture $actual_arch au lieu de $ARCH"
fi
echo "Architecture : $actual_arch"

smoke_api() {
  local name="smoke-api-$$" api="http://127.0.0.1:18000" metrics="http://127.0.0.1:19464"
  CONTAINER="$name"

  docker run -d --name "$name" "${HARDENING[@]}" \
    -p 127.0.0.1:18000:8000 -p 127.0.0.1:19464:9464 "$IMAGE" >/dev/null

  local ready=0
  for _ in $(seq 1 30); do
    if curl -fsS "$api/api/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" != "1" ]; then
    docker logs "$name" >&2 || true
    fail "l'API ne repond pas apres 30 s"
  fi
  echo "Sante : OK"

  [ "$(docker inspect -f '{{.Config.User}}' "$name")" = "lorakus" ] || fail "utilisateur de l'image inattendu"
  [ "$(docker exec "$name" id -u)" = "10001" ] || fail "l'API ne tourne pas avec l'uid 10001"
  echo "Utilisateur non-root : OK"

  if docker exec "$name" touch /app/intrusion 2>/dev/null; then
    fail "le systeme de fichiers de l'API est inscriptible"
  fi
  echo "Lecture seule : OK"

  # Page lue d'abord, cherchee ensuite : avec pipefail, « curl | grep -q » echoue au hasard
  # (grep ferme le tuyau des qu'il trouve, curl recoit SIGPIPE ; docs/runbooks/pitfalls.md).
  local page
  page=$(curl -fsS "$metrics/metrics") || fail "page des metriques injoignable"
  grep -qF 'lorakus_http_requests_total{method="GET",route="/api/health"' <<<"$page" \
    || fail "metrique des requetes absente"
  echo "Metriques : OK"

  docker logs "$name" 2>&1 | tail -n 1 | python3 -c 'import json, sys; json.loads(sys.stdin.read())' \
    || fail "la derniere ligne de journal n'est pas du JSON"
  echo "Journaux JSON : OK"
}

smoke_backup() {
  # On remplace le point d'entree par un shell pour interroger les outils sans lancer de sauvegarde.
  docker run --rm "${HARDENING[@]}" --entrypoint sh "$IMAGE" -c '
    set -e
    test "$(id -un)" = "postgres"
    ! command -v gosu >/dev/null
    pg_dump --version
    age --version
    rclone version | head -n 1
    test -x /usr/local/bin/lorakus-backup
  ' || fail "outils de sauvegarde incomplets"
  echo "Outils de sauvegarde : OK"
}

case "$KIND" in
  api) smoke_api ;;
  backup) smoke_backup ;;
  *) fail "type inconnu : $KIND (attendu : api ou backup)" ;;
esac

echo "Image $IMAGE ($ARCH) : verifications reussies"
