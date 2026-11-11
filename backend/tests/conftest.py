"""Outils partages par tous les tests (fixtures pytest).

Les fixtures de base de donnees ne se connectent que si un test les demande
(tests marques integration : make test-all).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from lorakus.api.app import create_app
from lorakus.core.identity.service import IdentityService
from lorakus.db.database import Database
from lorakus.settings import get_settings

OWNER_EMAIL = "anas@example.com"
OWNER_PASSWORD = "un mot de passe assez long"
BASE_URL = "https://testserver"  # cookie Secure : il n'est renvoye qu'en HTTPS


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Vide le cache des parametres avant et apres chaque test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    """Les tests asynchrones (@pytest.mark.anyio) tournent sur asyncio."""
    return "asyncio"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client HTTP de test branche directement sur l'application."""
    with TestClient(create_app()) as test_client:
        yield test_client


# ----------------------------------------------------------------- base reelle
def migrator_engine() -> AsyncEngine:
    """Role proprietaire : pour PREPARER et INSPECTER seulement, jamais pour verifier la RLS."""
    return create_async_engine(get_settings().migrator_database_url())


async def migrator_sql(
    sql: str, params: dict[str, object] | None = None
) -> list[tuple[object, ...]]:
    """Execute une requete en lorakus_migrator et renvoie les lignes."""
    engine = migrator_engine()
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), params or {})
            return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        await engine.dispose()


async def wipe_identity() -> None:
    """Vide les tables d'identite."""
    await migrator_sql(
        "TRUNCATE lorakus.core_sessions, lorakus.core_login_attempts, lorakus.core_users CASCADE"
    )


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """Base de l'application, role lorakus_app, tables d'identite videes."""
    await wipe_identity()
    db = Database.connect(get_settings())
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def identity(database: Database) -> IdentityService:
    """Service d'identite branche sur la base de test."""
    return IdentityService(database, get_settings())


@pytest.fixture
def api() -> Iterator[TestClient]:
    """Client HTTPS sur une application neuve, tables d'identite videes."""
    asyncio.run(wipe_identity())
    with TestClient(create_app(), base_url=BASE_URL) as test_client:
        yield test_client


def create_user_sync(email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD) -> None:
    """Cree le proprietaire depuis un test synchrone."""

    async def _create() -> None:
        settings = get_settings()
        db = Database.connect(settings)
        try:
            await IdentityService(db, settings).create_owner(email, password)
        finally:
            await db.close()

    asyncio.run(_create())
