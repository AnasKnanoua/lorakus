"""Tests de la route de sante et de la configuration de la documentation."""

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
    production_client = TestClient(create_app())

    assert production_client.get("/api/docs").status_code == 404
    assert production_client.get("/api/openapi.json").status_code == 404
