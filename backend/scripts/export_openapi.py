"""Ecrit le contrat OpenAPI de l'API, source du client TypeScript du frontend.

    uv run python scripts/export_openapi.py ../frontend/openapi.json

Sortie deterministe (cles triees) : la CI regenere le fichier et echoue s'il differe de
celui du depot, donc le client du frontend ne peut pas diverger de l'API.
Aucune base de donnees n'est necessaire (le cycle de vie de l'application n'est pas lance).
"""

import json
import sys
from pathlib import Path

from lorakus.api.app import create_app


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage : export_openapi.py FICHIER")
    schema = create_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    Path(sys.argv[1]).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
