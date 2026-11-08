"""Tests de l'observabilite : identifiant de requete, metriques, masquage, format JSON."""

import json
import logging

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from lorakus.observability.logging import REDACTED, configure_logging, redact_sensitive
from lorakus.observability.request_context import RequestContextMiddleware


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    request_id = client.get("/api/health").headers["x-request-id"]

    assert len(request_id) == 32
    int(request_id, 16)  # hexadecimal, sinon ValueError


def test_valid_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "trace-12345678"})

    assert response.headers["x-request-id"] == "trace-12345678"


@pytest.mark.parametrize(
    "suspicious_id",
    ["court", "x" * 65, "<script>alert(1)</script>", "id avec espaces"],
)
def test_suspicious_request_id_is_replaced(client: TestClient, suspicious_id: str) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": suspicious_id})

    assert response.headers["x-request-id"] != suspicious_id


def test_metrics_use_route_template_not_raw_path(client: TestClient) -> None:
    client.get("/api/health")
    client.get("/api/chemin-inexistant-42")

    exposed = generate_latest().decode()

    assert 'route="/api/health"' in exposed
    assert 'route="unmatched"' in exposed
    assert "chemin-inexistant-42" not in exposed


def test_route_template_with_nested_routers_and_parameter() -> None:
    items = APIRouter()

    @items.get("/items/{item_id}")
    async def read_item(item_id: int) -> int:
        return item_id

    v1 = APIRouter()
    v1.include_router(items, prefix="/v1")
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(v1, prefix="/api")

    TestClient(app).get("/api/v1/items/987654")

    exposed = generate_latest().decode()
    assert 'route="/api/v1/items/{item_id}"' in exposed
    assert "/api/v1/items/987654" not in exposed


def test_unknown_http_method_is_grouped(client: TestClient) -> None:
    client.request("FOOBAR", "/api/health")

    exposed = generate_latest().decode()

    assert 'method="FOOBAR"' not in exposed
    assert 'method="OTHER"' in exposed


def test_sensitive_values_are_masked() -> None:
    event = {
        "event": "connexion",
        "db_password": "s3cret",
        "api_key": "abc123",
        "url": "postgresql+psycopg://lorakus_app:s3cret@postgres:5432/lorakus",
    }

    masked = redact_sensitive(None, "info", event)

    assert masked["db_password"] == REDACTED
    assert masked["api_key"] == REDACTED
    assert "s3cret" not in masked["url"]


def test_logs_are_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(log_format="json")

    logging.getLogger("lorakus.test").info("evenement de test")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "evenement de test"
    assert payload["level"] == "info"
