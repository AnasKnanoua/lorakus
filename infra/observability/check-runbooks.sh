#!/usr/bin/env bash
# Verifie que chaque regle d'alerte renvoie a un runbook qui existe dans le depot.
# Execute par "make obs-check", donc en CI : un lien mort dans une alerte fait echouer la PR.
set -euo pipefail
cd "$(dirname "$0")/../.."

RULES=infra/observability/prometheus/rules/lorakus.yml
PREFIX=https://github.com/AnasKnanoua/lorakus/blob/main/

alerts=$(grep -cE '^[[:space:]]*- alert:' "$RULES")
links=$(grep -cE '^[[:space:]]*runbook_url:' "$RULES")
if [ "$alerts" -ne "$links" ]; then
  echo "ECHEC : $alerts regle(s) d'alerte mais $links annotation(s) runbook_url dans $RULES" >&2
  exit 1
fi

failed=0
while read -r url; do
  path=${url#"$PREFIX"}
  path=${path%%#*}
  if [ "$path" = "$url" ]; then
    echo "ECHEC : runbook_url hors du depot : $url" >&2
    failed=1
  elif [ ! -f "$path" ]; then
    echo "ECHEC : runbook introuvable : $path" >&2
    failed=1
  fi
done < <(sed -n 's/^[[:space:]]*runbook_url:[[:space:]]*//p' "$RULES" | sort -u)

[ "$failed" -eq 0 ] || exit 1
echo "Runbooks : $alerts regle(s), tous les liens pointent vers un fichier du depot."
