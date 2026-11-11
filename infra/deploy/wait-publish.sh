#!/usr/bin/env bash
# Attend que le workflow Publish ait fini pour le commit de main a deployer.
# Utilise par "make deploy" : sans cela, un deploiement lance juste apres une fusion
# cherche des images qui n'existent pas encore (incident du 2026-11-11).
set -euo pipefail

# Memes chemins que .github/workflows/publish.yml.
IMAGE_PATHS=(backend infra/backup infra/ci/smoke-image.sh .github/workflows/publish.yml)

git fetch --quiet origin main
sha=$(git rev-parse origin/main)
short=${sha:0:7}

if [ -z "$(git diff --name-only "${sha}^" "$sha" -- "${IMAGE_PATHS[@]}")" ]; then
  echo "Images inchangees par ${short} : rien a attendre."
  exit 0
fi

# Le run peut mettre quelques secondes a apparaitre apres la fusion.
run=""
for _ in $(seq 1 12); do
  run=$(gh run list --workflow publish.yml --commit "$sha" --limit 1 \
    --json databaseId --jq '.[0].databaseId // empty')
  [ -n "$run" ] && break
  sleep 5
done
[ -n "$run" ] || { echo "Aucune publication trouvee pour ${short} apres 60 s." >&2; exit 1; }

echo "Attente de la publication des images pour ${short} (quelques minutes)..."
if ! gh run watch "$run" --exit-status >/dev/null; then
  echo "La publication des images a echoue : deploiement annule." >&2
  echo "Voir docs/runbooks/deploy-failed.md (ligne 'denied' si c'est une premiere publication)." >&2
  exit 1
fi
echo "Images publiees pour ${short}."
