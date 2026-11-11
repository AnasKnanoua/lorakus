"""Connexion, sessions, cookie et changement de mot de passe, via l'API."""

import asyncio
import hashlib
import statistics
import time

import pytest
from conftest import BASE_URL, OWNER_EMAIL, OWNER_PASSWORD, create_user_sync, migrator_sql
from fastapi.testclient import TestClient

from lorakus.api.app import create_app
from lorakus.api.auth import SESSION_COOKIE

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def _login(api: TestClient, email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD) -> int:
    return api.post(LOGIN, json={"email": email, "password": password}).status_code


def _sql(sql: str, params: dict[str, object] | None = None) -> list[tuple[object, ...]]:
    return asyncio.run(migrator_sql(sql, params))


def test_login_sets_a_hardened_host_cookie(api: TestClient) -> None:
    create_user_sync()
    response = api.post(LOGIN, json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    lowered = cookie.lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/", "max-age="):
        assert attribute in lowered
    assert "domain=" not in lowered


def test_session_token_is_stored_hashed(api: TestClient) -> None:
    create_user_sync()
    _login(api)
    token = api.cookies[SESSION_COOKIE]

    stored = _sql("SELECT token_hash FROM lorakus.core_sessions")
    assert stored == [(hashlib.sha256(token.encode()).digest(),)]
    assert token.encode() not in stored[0][0]  # type: ignore[operator]


def test_me_requires_a_valid_session(api: TestClient) -> None:
    create_user_sync()
    assert api.get(ME).status_code == 401
    api.cookies.set(SESSION_COOKIE, "x" * 43)
    assert api.get(ME).status_code == 401
    api.cookies.clear()

    _login(api)
    response = api.get(ME)
    assert response.status_code == 200
    assert response.json()["email"] == OWNER_EMAIL
    assert response.json()["role"] == "owner"


def test_same_error_whether_or_not_the_account_exists(api: TestClient) -> None:
    create_user_sync()
    wrong_password = api.post(LOGIN, json={"email": OWNER_EMAIL, "password": "faux mot de passe"})
    unknown = api.post(
        LOGIN, json={"email": "inconnu@example.com", "password": "faux mot de passe"}
    )

    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json() == unknown.json() == {"detail": "Identifiants invalides."}


def test_email_is_case_and_space_insensitive(api: TestClient) -> None:
    create_user_sync()
    assert _login(api, email="  ANAS@Example.COM ") == 204


def test_idle_session_expires(api: TestClient) -> None:
    create_user_sync()
    _login(api)
    _sql("UPDATE lorakus.core_sessions SET last_seen_at = now() - interval '8 days'")

    assert api.get(ME).status_code == 401
    assert _sql("SELECT count(*) FROM lorakus.core_sessions") == [(0,)]


def test_session_expires_after_maximum_age_even_if_active(api: TestClient) -> None:
    create_user_sync()
    _login(api)
    _sql("UPDATE lorakus.core_sessions SET expires_at = now() - interval '1 second'")

    assert api.get(ME).status_code == 401


def test_logout_deletes_the_session(api: TestClient) -> None:
    create_user_sync()
    _login(api)
    token = api.cookies[SESSION_COOKIE]

    assert api.post("/api/v1/auth/logout").status_code == 204
    api.cookies.set(SESSION_COOKIE, token)
    assert api.get(ME).status_code == 401
    assert _sql("SELECT count(*) FROM lorakus.core_sessions") == [(0,)]


def test_password_change_revokes_every_session(api: TestClient) -> None:
    create_user_sync()
    with TestClient(create_app(), base_url=BASE_URL) as other_device:
        assert _login(other_device) == 204
        assert _login(api) == 204
        old_token = api.cookies[SESSION_COOKIE]

        response = api.post(
            "/api/v1/auth/password",
            json={"current_password": OWNER_PASSWORD, "new_password": "nouveau mot de passe long"},
        )
        assert response.status_code == 204

        assert other_device.get(ME).status_code == 401
        assert api.cookies[SESSION_COOKIE] != old_token
        assert api.get(ME).status_code == 200
        assert _sql("SELECT count(*) FROM lorakus.core_sessions") == [(1,)]
    assert _login(api, password=OWNER_PASSWORD) == 401
    assert _login(api, password="nouveau mot de passe long") == 204


def test_password_change_checks_the_current_password_and_policy(api: TestClient) -> None:
    create_user_sync()
    _login(api)
    wrong = api.post(
        "/api/v1/auth/password",
        json={"current_password": "pas le bon", "new_password": "nouveau mot de passe long"},
    )
    short = api.post(
        "/api/v1/auth/password",
        json={"current_password": OWNER_PASSWORD, "new_password": "court"},
    )
    assert wrong.status_code == 401
    assert short.status_code == 422
    assert api.get(ME).status_code == 200


def test_account_is_locked_after_repeated_failures(api: TestClient) -> None:
    create_user_sync()
    for _ in range(5):
        assert _login(api, password="mauvais mot de passe") == 401
    # Meme le bon mot de passe est refuse pendant la fenetre.
    assert _login(api) == 429
    # Un compte inexistant est limite exactement de la meme facon.
    for _ in range(5):
        assert _login(api, email="inconnu@example.com", password="mauvais mot de passe") == 401
    assert _login(api, email="inconnu@example.com", password="mauvais mot de passe") == 429


def test_success_resets_the_account_counter(api: TestClient) -> None:
    create_user_sync()
    for _ in range(4):
        _login(api, password="mauvais mot de passe")
    assert _login(api) == 204
    for _ in range(4):
        assert _login(api, password="mauvais mot de passe") == 401
    assert _login(api) == 204


def test_response_time_does_not_reveal_whether_the_account_exists(api: TestClient) -> None:
    create_user_sync()

    def median_ms(email: str) -> float:
        durations: list[float] = []
        for _ in range(4):
            start = time.perf_counter()
            api.post(LOGIN, json={"email": email, "password": "mauvais mot de passe"})
            durations.append((time.perf_counter() - start) * 1000)
            _sql("TRUNCATE lorakus.core_login_attempts")
        return statistics.median(durations)

    existing, unknown = median_ms(OWNER_EMAIL), median_ms("inconnu@example.com")
    # Le hachage (dizaines de ms) domine ; sans hachage factice, l'ecart serait de 100 %.
    assert abs(existing - unknown) / max(existing, unknown) < 0.35
