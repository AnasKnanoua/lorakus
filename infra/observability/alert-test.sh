#!/usr/bin/env bash
# Envoie une alerte de test a Alertmanager, qui la transmet a Discord.
#   alert-test.sh COMMANDE_COMPOSE...     ex. : alert-test.sh docker compose -f compose.yml ...
# Utilise par "make alert-test" (developpement) et "deploy.sh alert-test" (serveur).
#
# Une alerte injectee par amtool ne passe PAS par Prometheus : elle ne recoit donc pas ses
# external_labels. Le label "environment" est lu dans le conteneur Prometheus et ajoute ici,
# pour que le titre Discord porte bien [production], [staging] ou [development].
set -euo pipefail

[ "$#" -gt 0 ] || { echo "Usage : alert-test.sh COMMANDE_COMPOSE..." >&2; exit 2; }

# -T et </dev/null : docker compose exec ne doit jamais lire l'entree standard.
environment=$("$@" exec -T prometheus printenv LORAKUS_ENVIRONMENT </dev/null)
[[ "$environment" =~ ^[a-z]+$ ]] || { echo "Environnement illisible : '$environment'" >&2; exit 1; }

# amtool attend des valeurs entre guillemets doubles (d'ou les apostrophes autour).
"$@" exec -T alertmanager amtool alert add LorakusTest \
  'severity="warning"' 'component="test"' "environment=\"$environment\"" \
  --annotation='summary="Alerte de test Lorakus"' \
  --annotation='description="Envoyee a la main : aucune action attendue. Elle se resout seule en 5 minutes."' \
  --annotation='runbook_url="https://github.com/AnasKnanoua/lorakus/blob/main/docs/runbooks/README.md"' \
  --alertmanager.url=http://localhost:9093 </dev/null

echo "Alerte de test envoyee : [$environment] attendu dans le titre Discord, sous 30 secondes environ."
