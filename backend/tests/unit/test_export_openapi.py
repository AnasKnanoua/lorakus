"""Le contrat OpenAPI du frontend ne depend pas du numero de publication."""

import json
import subprocess
import sys
from pathlib import Path

from lorakus.api.app import create_app

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_openapi.py"


def test_the_contract_carries_the_api_version_not_the_release(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)  # noqa: S603

    contract = json.loads(out.read_text(encoding="utf-8"))

    assert contract["info"]["version"] == "v1"
    # La publication change de numero, l'API en service l'annonce toujours.
    assert create_app().openapi()["info"]["version"] != "v1"
