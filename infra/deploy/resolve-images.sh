#!/usr/bin/env bash
# Trouve les images publiees sur GHCR pour un commit de main.
#   resolve-images.sh COMMIT    ecrit IMAGE_COMMIT=, API_DIGEST= et BACKUP_DIGEST= sur la sortie
#
# Les images ne sont republiees que si leur code change : on prend le dernier commit (jusqu'a
# COMMIT inclus) qui a declenche le workflow Publish. Ces chemins doivent rester identiques a
# ceux de .github/workflows/publish.yml.
# Utilise par deploy.yml (staging puis production) ; a lancer depuis une copie complete du depot.
set -euo pipefail

commit="${1:-}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "Usage : resolve-images.sh COMMIT (40 caracteres)" >&2; exit 2; }
: "${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER manquant}"

image_commit=$(git log -1 --format=%H "$commit" -- \
  backend infra/backup infra/ci/smoke-image.sh .github/workflows/publish.yml)
[ -n "$image_commit" ] || { echo "Aucun commit d'image avant $commit" >&2; exit 1; }

owner="${GITHUB_REPOSITORY_OWNER,,}"
digest_of() {
  docker buildx imagetools inspect "ghcr.io/${owner}/$1:sha-${image_commit}" \
    --format '{{json .Manifest}}' | jq -r '.digest'
}
api=$(digest_of lorakus-api)
backup=$(digest_of lorakus-backup)
for d in "$api" "$backup"; do
  if [[ ! "$d" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Image introuvable pour le commit ${image_commit} : le workflow Publish a-t-il reussi ?" >&2
    exit 1
  fi
done

echo "IMAGE_COMMIT=$image_commit"
echo "API_DIGEST=$api"
echo "BACKUP_DIGEST=$backup"
