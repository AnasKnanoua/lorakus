"""Chaque secret ne va qu'aux services qui en ont besoin (compose.yml).

Garde-fou ajoute apres le 2026-11-11 : la cle de chiffrement avait ete donnee a PostgreSQL
au lieu de l'API ; l'API refusait de demarrer en staging, et la cle sortait de son perimetre.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "compose.yml"

# Secret -> services autorises a le recevoir.
ALLOWED = {
    "LORAKUS_FIELD_ENCRYPTION_KEY": {"api"},
    "LORAKUS_APP_DB_PASSWORD": {"postgres", "api", "worker"},
    "BACKUP_AGE_RECIPIENT": {"backup"},
}


def _services() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text("utf-8"))["services"]


@pytest.mark.parametrize("secret", sorted(ALLOWED))
def test_secret_reaches_only_its_services(secret: str) -> None:
    receivers = {
        name
        for name, service in _services().items()
        if secret in (service.get("environment") or {})
    }
    assert receivers == ALLOWED[secret]
