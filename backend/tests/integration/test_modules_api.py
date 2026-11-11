"""Activation par utilisateur, montage des routes et sante des modules, via l'API."""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from conftest import (
    BASE_URL,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    create_user_sync,
    migrator_sql,
    wipe_identity,
)
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from lorakus.api.app import create_app
from lorakus.core.modules.manifest import ModuleManifest
from lorakus.core.modules.registry import ModuleRegistry

pytestmark = pytest.mark.integration


class AlphaConfig(BaseModel):
    threshold: int = Field(default=3, ge=1, le=10)


def _module(module_id: str, **extra: Any) -> ModuleManifest:
    router = APIRouter()

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"module": module_id}

    return ModuleManifest(
        id=module_id,
        name=module_id.capitalize(),
        version="0.1.0",
        requires_core=">=0.1,<1.0",
        description=f"Module {module_id}",
        api_router=router,
        **extra,
    )


async def _healthy() -> bool:
    return True


async def _broken() -> bool:
    raise RuntimeError("panne")


@pytest.fixture
def modules_client() -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    registry = ModuleRegistry(
        [
            _module("alpha", config_schema=AlphaConfig, health=_healthy),
            _module("beta", depends_on=["alpha"], health=_broken),
        ]
    )
    with TestClient(create_app(registry), base_url=BASE_URL) as client:
        create_user_sync()
        response = client.post(
            "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        )
        assert response.status_code == 204
        yield client


def _put(client: TestClient, module_id: str, enabled: bool, config: object = None) -> int:
    body: dict[str, object] = {"enabled": enabled}
    if config is not None:
        body["config"] = config
    return client.put(f"/api/v1/modules/{module_id}", json=body).status_code


def test_modules_are_disabled_by_default_and_their_routes_hidden(
    modules_client: TestClient,
) -> None:
    listed = modules_client.get("/api/v1/modules").json()
    assert [(m["id"], m["enabled"]) for m in listed] == [("alpha", False), ("beta", False)]
    assert listed[0]["config_schema"]["properties"]["threshold"]["maximum"] == 10
    assert modules_client.get("/api/v1/alpha/ping").status_code == 404


def test_module_routes_require_a_session(modules_client: TestClient) -> None:
    assert _put(modules_client, "alpha", True) == 200
    with TestClient(modules_client.app, base_url=BASE_URL) as anonymous:  # type: ignore[arg-type]
        assert anonymous.get("/api/v1/alpha/ping").status_code == 401


def test_enable_configure_and_disable(modules_client: TestClient) -> None:
    assert _put(modules_client, "alpha", True, {"threshold": 99}) == 422
    assert _put(modules_client, "alpha", True, {"threshold": 5}) == 200
    assert modules_client.get("/api/v1/alpha/ping").json() == {"module": "alpha"}
    assert modules_client.get("/api/v1/modules").json()[0]["config"] == {"threshold": 5}
    assert _put(modules_client, "alpha", False) == 200
    assert modules_client.get("/api/v1/alpha/ping").status_code == 404
    assert _put(modules_client, "inconnu", True) == 404


def test_dependencies_are_enforced(modules_client: TestClient) -> None:
    assert _put(modules_client, "beta", True) == 409
    assert _put(modules_client, "alpha", True) == 200
    assert _put(modules_client, "beta", True) == 200
    assert _put(modules_client, "alpha", False) == 409
    assert _put(modules_client, "beta", False) == 200
    assert _put(modules_client, "alpha", False) == 200


def test_changes_are_audited(modules_client: TestClient) -> None:
    _put(modules_client, "alpha", True)
    _put(modules_client, "alpha", False)
    events = [
        (e["action"], e["details"].get("module"))
        for e in modules_client.get("/api/v1/auth/audit").json()
        if e["action"].startswith("modules.")
    ]
    assert events == [("modules.disable", "alpha"), ("modules.enable", "alpha")]


def test_health_is_owner_only_and_survives_a_broken_module(modules_client: TestClient) -> None:
    assert modules_client.get("/api/v1/modules/health").json() == {"alpha": "ok", "beta": "error"}
    asyncio.run(migrator_sql("UPDATE lorakus.core_users SET role = 'admin'"))
    assert modules_client.get("/api/v1/modules/health").status_code == 403


def test_module_states_are_isolated_between_users(modules_client: TestClient) -> None:
    _put(modules_client, "alpha", True)
    other = uuid.uuid4()
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, 'b@example.com', 'x', 'user')",
            {"id": other},
        )
    )
    rows = asyncio.run(
        migrator_sql("SELECT user_id FROM lorakus.core_user_modules WHERE module_id = 'alpha'")
    )
    assert len(rows) == 1
    assert rows[0][0] != other
