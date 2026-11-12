"""Controle de l'origine des ecritures (PR 35)."""

import pytest
from fastapi.testclient import TestClient

from lorakus.api.app import create_app
from lorakus.api.origin import origin_allowed

APP = frozenset({"https://app.lorakus.app"})


@pytest.mark.parametrize(
    ("method", "origin", "fetch_site", "expected"),
    [
        ("GET", "https://evil.example", "cross-site", True),  # lecture : jamais bloquee ici
        ("POST", None, None, True),  # client sans navigateur (script, cle d'API)
        ("POST", "https://app.lorakus.app", "same-origin", True),
        ("POST", "https://app.lorakus.app", None, True),  # navigateur ancien
        ("POST", "https://evil.example", None, False),
        ("POST", "null", None, False),  # iframe isolee, redirection
        ("POST", None, "cross-site", False),
        ("DELETE", "https://staging.lorakus.app", "same-site", False),  # sous-domaine voisin
        ("PATCH", "https://app.lorakus.app:8443", None, False),  # autre port, autre origine
        ("PUT", "http://app.lorakus.app", None, False),  # HTTP au lieu de HTTPS
    ],
)
def test_origin_decision(
    method: str, origin: str | None, fetch_site: str | None, expected: bool
) -> None:
    assert origin_allowed(method, origin, fetch_site, APP) is expected


def test_cross_origin_write_is_refused_before_reaching_the_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LORAKUS_PUBLIC_ORIGIN", "https://app.lorakus.app")
    client = TestClient(create_app())
    body = {"email": "a@example.com", "password": "x"}

    refused = client.post(
        "/api/v1/auth/login", json=body, headers={"Origin": "https://evil.example"}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "origin_refused"
    assert refused.headers["X-Request-ID"]  # passe quand meme par le journal d'acces

    # Lecture depuis une autre origine : la route repond normalement.
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200


def test_development_allows_the_vite_dev_server() -> None:
    client = TestClient(create_app())
    headers = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}
    # 405 : le controle laisse passer, c'est la route qui refuse la methode.
    assert client.post("/api/health", headers=headers).status_code == 405
    assert client.post("/api/health", headers={"Origin": "https://evil.example"}).status_code == 403
