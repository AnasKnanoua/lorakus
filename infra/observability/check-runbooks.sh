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

# Ancres des titres d'un fichier Markdown, calculees comme GitHub pour les titres en ASCII :
# minuscules, ponctuation retiree, espaces remplaces par des tirets. Un titre accentue donne une
# ancre differente de celle de GitHub : l'ancre d'un lien d'alerte doit donc viser un titre en
# ASCII (le nom de l'alerte), sinon ce controle echoue (jamais l'inverse).
anchors() {
  sed -n 's/^#\{1,6\}[[:space:]]\{1,\}//p' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | LC_ALL=C sed 's/[^a-z0-9 _-]//g; s/ /-/g'
}

failed=0
while read -r url; do
  path=${url#"$PREFIX"}
  anchor=
  case "$path" in *#*) anchor=${path#*#} ;; esac
  path=${path%%#*}
  if [ "$path" = "${url%%#*}" ]; then
    echo "ECHEC : runbook_url hors du depot : $url" >&2
    failed=1
  elif [ ! -f "$path" ]; then
    echo "ECHEC : runbook introuvable : $path" >&2
    failed=1
  # Liste lue d'abord, cherchee ensuite : jamais "commande | grep -q" (pitfalls.md).
  elif [ -n "$anchor" ] && ! grep -qxF -- "$anchor" <<<"$(anchors "$path")"; then
    echo "ECHEC : aucun titre de $path ne donne l'ancre #$anchor" >&2
    failed=1
  fi
done < <(sed -n 's/^[[:space:]]*runbook_url:[[:space:]]*//p' "$RULES" | sort -u)

[ "$failed" -eq 0 ] || exit 1
echo "Runbooks : $alerts regle(s), tous les liens pointent vers un fichier et un titre du depot."
