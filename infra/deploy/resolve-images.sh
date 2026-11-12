#!/usr/bin/env bash
# Trouve les images publiees sur GHCR pour un commit de main.
#   resolve-images.sh COMMIT [--web-optional]
#     ecrit IMAGE_COMMIT=, API_DIGEST=, BACKUP_DIGEST=, WEB_IMAGE_COMMIT= et WEB_DIGEST=
#
# Les images ne sont republiees que si leur code change : on prend le dernier commit (jusqu'a
# COMMIT inclus) qui a modifie leurs fichiers. Ces chemins doivent rester inclus dans ceux qui
# declenchent .github/workflows/publish.yml.
# --web-optional : pour une version anterieure a l'image web (PR 35), WEB_DIGEST reste vide
# au lieu d'echouer. Sans cette option, une image web introuvable est une erreur.
# Utilise par deploy.yml (staging puis production) ; a lancer depuis une copie complete du depot.
set -euo pipefail

commit="${1:-}"
web_optional="${2:-}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "Usage : resolve-images.sh COMMIT [--web-optional]" >&2; exit 2; }
[ -z "$web_optional" ] || [ "$web_optional" = "--web-optional" ] || { echo "Option inconnue : $web_optional" >&2; exit 2; }
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER manquant}"

last_commit() {
  git log -1 --format=%H "$commit" -- "$@"
}

image_commit=$(last_commit backend infra/backup infra/ci/smoke-image.sh .github/workflows/publish.yml)
[ -n "$image_commit" ] || { echo "Aucun commit d'image avant $commit" >&2; exit 1; }
web_commit=$(last_commit frontend infra/web infra/ci/smoke-image.sh .github/workflows/publish.yml)

owner="${GITHUB_REPOSITORY_OWNER,,}"
digest_of() {
  docker buildx imagetools inspect "ghcr.io/${owner}/$1:sha-$2" \
    --format '{{json .Manifest}}' 2>/dev/null | jq -r '.digest' || true
}
valid() {
  [[ "$1" =~ ^sha256:[0-9a-f]{64}$ ]]
}

api=$(digest_of lorakus-api "$image_commit")
backup=$(digest_of lorakus-backup "$image_commit")
for d in "$api" "$backup"; do
  if ! valid "$d"; then
    echo "Image introuvable pour le commit ${image_commit} : le workflow Publish a-t-il reussi ?" >&2
    exit 1
  fi
done

web=$(digest_of lorakus-web "$web_commit")
if ! valid "$web"; then
  if [ "$web_optional" != "--web-optional" ]; then
    echo "Image web introuvable pour le commit ${web_commit} : le workflow Publish a-t-il reussi ?" >&2
    exit 1
  fi
  web=""
  web_commit=""
fi

echo "IMAGE_COMMIT=$image_commit"
echo "API_DIGEST=$api"
echo "BACKUP_DIGEST=$backup"
echo "WEB_IMAGE_COMMIT=$web_commit"
echo "WEB_DIGEST=$web"
