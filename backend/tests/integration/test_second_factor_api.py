"""Double authentification, re-authentification et codes de secours, via l'API."""

import asyncio
import time

import pytest
from conftest import OWNER_EMAIL, OWNER_PASSWORD, create_user_sync, migrator_sql
from fastapi.testclient import TestClient

from lorakus.core.identity import totp

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"


def _sql(sql: str) -> list[tuple[object, ...]]:
    return asyncio.run(migrator_sql(sql))


def _login(api: TestClient, second_factor: str | None = None) -> tuple[int, object]:
    body: dict[str, object] = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    if second_factor is not None:
        body["second_factor"] = second_factor
    response = api.post(LOGIN, json=body)
    return response.status_code, (response.json() if response.content else None)


def _enable_totp(api: TestClient) -> tuple[str, list[str]]:
    secret = api.post("/api/v1/auth/totp/setup").json()["secret"]
    step = totp.current_step(time.time())
    response = api.post("/api/v1/auth/totp/confirm", json={"code": totp.code_at(secret, step)})
    assert response.status_code == 200
    return secret, response.json()["backup_codes"]


@pytest.fixture
def logged_in(api: TestClient) -> TestClient:
    create_user_sync()
    assert _login(api)[0] == 204
    return api


def test_sensitive_actions_need_a_recent_proof_of_identity(logged_in: TestClient) -> None:
    _sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '11 minutes'")
    response = logged_in.post("/api/v1/auth/totp/setup")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "reauth_required"

    wrong = logged_in.post("/api/v1/auth/reauth", json={"password": "pas le bon mot de passe"})
    assert wrong.status_code == 401
    assert (
        logged_in.post("/api/v1/auth/reauth", json={"password": OWNER_PASSWORD}).status_code == 204
    )
    assert logged_in.post("/api/v1/auth/totp/setup").status_code == 200


def test_totp_secret_is_encrypted_at_rest(logged_in: TestClient) -> None:
    secret = logged_in.post("/api/v1/auth/totp/setup").json()["secret"]
    [(stored,)] = _sql("SELECT secret_encrypted FROM lorakus.core_totp")
    assert isinstance(stored, str)
    assert stored.startswith("v1:")
    assert secret not in stored


def test_full_second_factor_flow(logged_in: TestClient) -> None:
    secret, backup_codes = _enable_totp(logged_in)
    assert len(backup_codes) == 10
    assert logged_in.get("/api/v1/auth/me").json()["totp_enabled"] is True
    stored_codes = _sql("SELECT code_hash FROM lorakus.core_backup_codes")
    assert len(stored_codes) == 10
    stored = [bytes(row[0]) for row in stored_codes]  # type: ignore[arg-type]
    assert all(
        code.replace("-", "").encode() not in value for code in backup_codes for value in stored
    )
    logged_in.post("/api/v1/auth/logout")

    status, body = _login(logged_in)
    assert status == 401
    assert isinstance(body, dict)
    assert body["detail"]["code"] == "second_factor_required"

    # Le code deja utilise a la confirmation ne passe plus (anti-rejeu).
    step = totp.current_step(time.time())
    assert _login(logged_in, totp.code_at(secret, step))[0] == 401
    next_code = totp.code_at(secret, step + 1)
    assert _login(logged_in, next_code)[0] == 204
    # ... et le code qui vient d'ouvrir la session non plus.
    assert _login(logged_in, next_code)[0] == 401


def test_backup_code_works_exactly_once(logged_in: TestClient) -> None:
    _, backup_codes = _enable_totp(logged_in)
    code = backup_codes[3].upper().replace("-", " ")
    assert _login(logged_in, code)[0] == 204
    assert _login(logged_in, code)[0] == 401
    assert _sql("SELECT count(*) FROM lorakus.core_backup_codes WHERE used_at IS NOT NULL") == [
        (1,)
    ]


def test_wrong_codes_lock_the_account(logged_in: TestClient) -> None:
    _enable_totp(logged_in)
    for _ in range(5):
        assert _login(logged_in, "000000")[0] == 401
    secret_free_status, _ = _login(logged_in)
    assert secret_free_status == 429


def test_disable_requires_recent_auth_and_removes_everything(logged_in: TestClient) -> None:
    _enable_totp(logged_in)
    _sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '1 hour'")
    assert logged_in.post("/api/v1/auth/totp/disable").status_code == 403
    _sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now()")
    assert logged_in.post("/api/v1/auth/totp/disable").status_code == 204
    assert _sql(
        "SELECT (SELECT count(*) FROM lorakus.core_totp), "
        "(SELECT count(*) FROM lorakus.core_backup_codes)"
    ) == [(0, 0)]
    assert _login(logged_in)[0] == 204


def test_cannot_set_up_twice(logged_in: TestClient) -> None:
    _enable_totp(logged_in)
    assert logged_in.post("/api/v1/auth/totp/setup").status_code == 409


def test_wrong_confirmation_code_keeps_it_disabled(logged_in: TestClient) -> None:
    logged_in.post("/api/v1/auth/totp/setup")
    assert logged_in.post("/api/v1/auth/totp/confirm", json={"code": "000000"}).status_code == 400
    assert logged_in.get("/api/v1/auth/me").json()["totp_enabled"] is False
    assert _login(logged_in)[0] == 204
