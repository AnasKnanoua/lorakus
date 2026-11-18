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
    # ...et la table visee existe toujours (une ligne par branche : Core et chaque module).
    assert versions >= 1


@pytest.mark.anyio
async def test_database_errors_never_carry_the_values_of_the_query() -> None:
    """Une erreur SQL part au journal (puis a Loki) : jamais avec les valeurs, qui peuvent etre
    une question, un souvenir ou un message (PR 41)."""
    database = Database.connect(get_settings())
    secret = "souvenir-tres-personnel"
    try:
        async with database.engine.connect() as connection:
            with pytest.raises(Exception, match="hidden") as raised:
                await connection.execute(
                    text("SELECT CAST(:value AS text)"), {"value": f"{secret}\x00"}
                )
    finally:
        await database.close()
    assert secret not in str(raised.value)
