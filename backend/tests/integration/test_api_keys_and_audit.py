"""Cles d'API (portees, expiration, revocation) et journal d'audit en ajout seul."""

import asyncio
import hashlib
from collections.abc import Iterator
from typing import Annotated

import pytest
from conftest import BASE_URL, OWNER_EMAIL, OWNER_PASSWORD, create_user_sync, migrator_sql
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from lorakus.api.app import create_app
from lorakus.api.auth import api_key
from lorakus.core.identity.service import ApiPrincipal
from lorakus.db.database import Database

pytestmark = pytest.mark.integration

KEYS = "/api/v1/auth/api-keys"


def _sql(sql: str) -> list[tuple[object, ...]]:
    return asyncio.run(migrator_sql(sql))


@pytest.fixture
def client(api: TestClient) -> Iterator[TestClient]:
    """Application avec une route de test protegee par la portee inbox:write."""
    app = api.app

    @app.get("/test/inbox")  # type: ignore[union-attr]
    async def inbox(
        caller: Annotated[ApiPrincipal, Depends(api_key("inbox:write"))],
    ) -> dict[str, str]:
        return {"user_id": str(caller.user_id)}

    create_user_sync()
    response = api.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert response.status_code == 204
    yield api


def _create(
    client: TestClient, scopes: list[str] | None = None, days: int = 30
) -> dict[str, object]:
    response = client.post(
        KEYS,
        json={"name": "telephone", "scopes": scopes or ["inbox:write"], "expires_in_days": days},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _call(key: str) -> int:
    with TestClient(create_app(), base_url=BASE_URL) as anonymous:
        return anonymous.get("/test/inbox", headers={"Authorization": f"Bearer {key}"}).status_code


def test_key_is_shown_once_and_stored_hashed(client: TestClient) -> None:
    created = _create(client)
    key = str(created["key"])
    assert key.startswith(f"{created['prefix']}_")

    listed = client.get(KEYS).json()
    assert [item["prefix"] for item in listed] == [created["prefix"]]
    assert "key" not in listed[0]
    [(stored,)] = _sql("SELECT key_hash FROM lorakus.core_api_keys")
    assert stored == hashlib.sha256(key.encode()).digest()


def test_key_grants_only_its_scopes(client: TestClient) -> None:
    good = str(_create(client)["key"])
    other = str(_create(client, ["usage:write"])["key"])
    app = client.app
    with TestClient(app, base_url=BASE_URL) as anonymous:  # type: ignore[arg-type]
        assert (
            anonymous.get("/test/inbox", headers={"Authorization": f"Bearer {good}"}).status_code
            == 200
        )
        assert (
            anonymous.get("/test/inbox", headers={"Authorization": f"Bearer {other}"}).status_code
            == 403
        )
        assert anonymous.get("/test/inbox").status_code == 401
        assert (
            anonymous.get("/test/inbox", headers={"Authorization": f"Bearer {good}x"}).status_code
            == 401
        )
        forged = good[:-1] + ("A" if good[-1] != "A" else "B")
        assert (
            anonymous.get("/test/inbox", headers={"Authorization": f"Bearer {forged}"}).status_code
            == 401
        )


def test_revoked_and_expired_keys_are_refused(client: TestClient) -> None:
    revoked = _create(client)
    expired = _create(client)
    assert client.delete(f"{KEYS}/{revoked['id']}").status_code == 204
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_api_keys SET expires_at = now() - interval '1 second' "
            "WHERE id = :id",
            {"id": expired["id"]},
        )
    )
    app = client.app
    with TestClient(app, base_url=BASE_URL) as anonymous:  # type: ignore[arg-type]
        for item in (revoked, expired):
            response = anonymous.get(
                "/test/inbox", headers={"Authorization": f"Bearer {item['key']}"}
            )
            assert response.status_code == 401
    denied = _sql(
        "SELECT details->>'reason' FROM lorakus.core_audit_events "
        "WHERE action = 'auth.api_key_use' ORDER BY id"
    )
    assert denied == [("revoked",), ("expired",)]


def test_key_creation_rules(client: TestClient) -> None:
    for body in (
        {"name": "x", "scopes": ["admin:all"], "expires_in_days": 30},
        {"name": "x", "scopes": [], "expires_in_days": 30},
        {"name": "x", "scopes": ["inbox:write"], "expires_in_days": 366},
        {"name": "x", "scopes": ["inbox:write"], "expires_in_days": 0},
    ):
        assert client.post(KEYS, json=body).status_code == 422
    _sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '1 hour'")
    assert (
        client.post(
            KEYS, json={"name": "x", "scopes": ["inbox:write"], "expires_in_days": 30}
        ).status_code
        == 403
    )


def test_security_events_are_audited_without_secrets(client: TestClient) -> None:
    key = str(_create(client)["key"])
    client.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": "mauvais mot de passe"}
    )
    events = client.get("/api/v1/auth/audit").json()
    actions = [(event["action"], event["outcome"]) for event in events]
    assert ("auth.login", "failure") in actions
    assert ("auth.api_key_create", "success") in actions
    assert ("auth.login", "success") in actions
    assert ("auth.owner_create", "success") in actions
    everything = str(_sql("SELECT details FROM lorakus.core_audit_events"))
    secret_part = key.rsplit("_", 1)[1]
    assert secret_part not in everything
    assert OWNER_PASSWORD not in everything


@pytest.mark.anyio
async def test_audit_log_is_append_only_for_the_application(database: Database) -> None:
    for statement in (
        "UPDATE lorakus.core_audit_events SET outcome = 'success'",
        "DELETE FROM lorakus.core_audit_events",
        "TRUNCATE lorakus.core_audit_events",
        "INSERT INTO lorakus.core_audit_events (action, outcome) VALUES ('faux', 'success')",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with database.transaction() as session:
                await session.execute(text(statement))
    # Seul chemin d'ecriture : la fonction, qui n'ajoute qu'une ligne.
    async with database.transaction() as session:
        await session.execute(
            text("SELECT lorakus.audit_record(NULL, 'test', 'success', NULL, '{}'::jsonb)")
        )
    assert await migrator_sql(
        "SELECT count(*) FROM lorakus.core_audit_events WHERE action = 'test'"
    ) == [(1,)]


@pytest.mark.anyio
async def test_users_only_read_their_own_audit_events(database: Database) -> None:
    import uuid

    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_audit_events (user_id, action, outcome) "
        "VALUES (:a, 'a', 'success'), (:b, 'b', 'success'), (NULL, 'anonyme', 'failure')",
        {"a": mine, "b": theirs},
    )
    async with database.transaction(mine) as session:
        actions = (
            (await session.execute(text("SELECT action FROM lorakus.core_audit_events")))
            .scalars()
            .all()
        )
    assert actions == ["a"]
