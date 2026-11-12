"""Tests des routes de sante et de la configuration de la documentation."""

import pytest
from fastapi.testclient import TestClient

from lorakus.api.app import create_app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_docs_available_in_development(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200


def test_docs_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORAKUS_ENVIRONMENT", "production")
    monkeypatch.setenv("LORAKUS_APP_DB_PASSWORD", "test-only")
    monkeypatch.setenv("LORAKUS_PUBLIC_ORIGIN", "https://app.example.test")
    production_client = TestClient(create_app())

    assert production_client.get("/api/docs").status_code == 404
    assert production_client.get("/api/openapi.json").status_code == 404


def test_ready_returns_503_without_details_when_database_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Port 1 : aucune base n'y ecoute, la connexion est refusee immediatement.
    monkeypatch.setenv("LORAKUS_DB_PORT", "1")

    with TestClient(create_app()) as unreachable_client:
        response = unreachable_client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_api_refuses_to_start_without_public_origin(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("LORAKUS_ENVIRONMENT", environment)
    monkeypatch.delenv("LORAKUS_PUBLIC_ORIGIN", raising=False)
    with pytest.raises(ValueError, match="LORAKUS_PUBLIC_ORIGIN"):
        create_app()
