"""Outils partages par tous les tests (fixtures pytest)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lorakus.api.app import create_app
from lorakus.settings import get_settings


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
