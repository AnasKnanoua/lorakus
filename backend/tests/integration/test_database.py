"""Tests d'integration : necessitent PostgreSQL (make test-all)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from lorakus.db.database import Database
from lorakus.settings import get_settings

pytestmark = pytest.mark.integration

MALICIOUS = "x'; DROP TABLE alembic_version; --"


def test_ready_ok_with_real_database(client: TestClient) -> None:
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_malicious_input_is_treated_as_data() -> None:
    database = Database.connect(get_settings())
    try:
        async with database.engine.connect() as connection:
            echoed = await connection.scalar(
                text("SELECT CAST(:value AS text)"), {"value": MALICIOUS}
            )
            versions = await connection.scalar(text("SELECT count(*) FROM alembic_version"))
    finally:
        await database.close()

    # La base a renvoye la chaine telle quelle, sans l'executer...
    assert echoed == MALICIOUS
    # ...et la table visee existe toujours.
    assert versions == 1
