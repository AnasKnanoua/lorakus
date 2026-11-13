#!/usr/bin/env bash
# Verifie qu'une image construite demarre et respecte nos regles de securite.
# A lancer sur une machine de la meme architecture que l'image (pas d'emulation).
#   smoke-image.sh api    IMAGE ARCH    demarre l'API et l'interroge
#   smoke-image.sh backup IMAGE ARCH    verifie les outils de sauvegarde
#   smoke-image.sh web    IMAGE ARCH    demarre Caddy (certificat local) et verifie l'interface
# ARCH vaut amd64 ou arm64.
set -euo pipefail

KIND="${1:?usage: smoke-image.sh api|backup|web IMAGE ARCH}"
IMAGE="${2:?usage: smoke-image.sh api|backup|web IMAGE ARCH}"
ARCH="${3:?usage: smoke-image.sh api|backup|web IMAGE ARCH}"

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

  # Modele d'embeddings integre a l'image (PR 37) : charge, dimension, sens en francais, et
  # mesures (memoire, latence) sur cette architecture, lisibles dans le journal de la CI.
  docker exec "$name" python -m lorakus.ai.providers.check \
    || fail "modele d'embeddings absent ou defaillant"
  echo "Modele d'embeddings : OK"
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

smoke_web() {
  local name="smoke-web-$$" https="https://localhost:18443" headers page
  CONTAINER="$name"

  # Memes protections que compose.prod.yml ; /data en memoire (certificat local jetable).
  docker run -d --name "$name" "${HARDENING[@]}" \
    --tmpfs /config:size=1m,uid=10002,gid=10002 --tmpfs /data:size=16m,uid=10002,gid=10002 \
    -e LORAKUS_PUBLIC_HOST=localhost -e LORAKUS_TLS=internal \
    -p 127.0.0.1:18080:8080 -p 127.0.0.1:18443:8443 -p 127.0.0.1:18081:8081 "$IMAGE" >/dev/null

  local ready=0
  for _ in $(seq 1 30); do
    if curl -fsk -o /dev/null "$https/"; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" != "1" ]; then
    docker logs "$name" >&2 || true
    fail "Caddy ne repond pas en HTTPS apres 30 s"
  fi
  curl -fsS -o /dev/null http://127.0.0.1:18081/healthz || fail "sante (8081) injoignable"
  echo "HTTPS et sante : OK"

  [ "$(docker exec "$name" id -u)" = "10002" ] || fail "Caddy ne tourne pas avec l'uid 10002"
  if docker exec "$name" touch /srv/intrusion 2>/dev/null; then
    fail "les fichiers de l'interface sont modifiables"
  fi
  echo "Utilisateur non-root et lecture seule : OK"

  # Reponse lue d'abord, cherchee ensuite (tuyau et pipefail : docs/runbooks/pitfalls.md).
  headers=$(curl -fsSk -D - -o /dev/null "$https/")
  for expected in "content-security-policy: default-src 'self'; script-src 'self';" \
    "strict-transport-security: max-age=31536000" "x-content-type-options: nosniff" \
    "x-frame-options: DENY" "referrer-policy: no-referrer"; do
    grep -qiF "$expected" <<<"$headers" || fail "en-tete absent : $expected"
  done
  if grep -qi '^server:' <<<"$headers"; then
    fail "l'en-tete Server revele le logiciel"
  fi
  echo "En-tetes de securite : OK"

  page=$(curl -fsSk "$https/une/adresse/profonde") || fail "lien profond en echec"
  grep -qF '<div id="root">' <<<"$page" || fail "le lien profond ne renvoie pas l'interface"
  headers=$(curl -sS -o /dev/null -D - -H "Host: localhost" http://127.0.0.1:18080/a?b=1)
  grep -qiF "location: https://localhost/a?b=1" <<<"$headers" || fail "redirection HTTP -> HTTPS absente"
  echo "Interface et redirection : OK"
}

case "$KIND" in
  api) smoke_api ;;
  backup) smoke_backup ;;
  web) smoke_web ;;
  *) fail "type inconnu : $KIND (attendu : api, backup ou web)" ;;
esac

echo "Image $IMAGE ($ARCH) : verifications reussies"
