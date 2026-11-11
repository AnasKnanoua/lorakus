"""Outils (confirmation, audit) et specialistes factices (critere de fin de la phase 2)."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
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
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import text

from lorakus.api.app import create_app
from lorakus.core.agents.contract import (
    Confidence,
    Fact,
    SpecialistContext,
    SpecialistProfile,
    SpecialistReport,
)
from lorakus.core.modules.manifest import ModuleManifest
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.tools.spec import ToolCall, ToolSpec

pytestmark = pytest.mark.integration
executed: list[tuple[str, Any, Any]] = []


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=50)


class Empty(BaseModel):
    pass


async def _whoami(call: ToolCall, _args: Empty) -> dict[str, Any]:
    current = await call.session.scalar(text("SELECT lorakus.current_user_id()"))
    return {"user": str(current)}


async def _add_note(call: ToolCall, args: NoteIn) -> dict[str, Any]:
    executed.append(("add", call.user_id, args.text))
    return {"saved": args.text}


async def _pay(call: ToolCall, args: NoteIn) -> dict[str, Any]:
    executed.append(("pay", call.user_id, args.text))
    return {"paid": True}


async def _alpha(ctx: SpecialistContext) -> SpecialistReport:
    async with ctx.open_transaction() as session:
        current = await session.scalar(text("SELECT lorakus.current_user_id()"))
    return SpecialistReport(
        status="ok",
        summary=f"Trois revisions prevues. Utilisateur {str(current)[:8]}.",
        facts=[
            Fact(label="revisions", value="3", data_class="personal", source="alpha", measured=True)
        ],
        confidence=Confidence(level=0.8, reason="donnees du jour"),
        freshness=datetime.now(UTC),
    )


async def _beta_slow(_ctx: SpecialistContext) -> SpecialistReport:
    await asyncio.sleep(5)
    return SpecialistReport(status="no_data", summary="Rien.")


async def _gamma_leaky(_ctx: SpecialistContext) -> SpecialistReport:
    return SpecialistReport(
        status="ok",
        summary="Solde du compte.",
        facts=[
            Fact(
                label="solde", value="1200", data_class="sensitive", source="banque", measured=True
            )
        ],
        confidence=Confidence(level=1, reason="releve"),
    )


def _module(module_id: str, **extra: Any) -> ModuleManifest:
    return ModuleManifest(
        id=module_id,
        name=module_id,
        version="0.1.0",
        requires_core=">=0.1,<1.0",
        description="Module factice",
        **extra,
    )


def _profile(name: str, handler: Any, intent: str, **extra: Any) -> SpecialistProfile:
    return SpecialistProfile(
        name=name,
        display_name=name.capitalize(),
        intents=[intent],
        limits="Factice.",
        handler=handler,
        **extra,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    executed.clear()
    registry = ModuleRegistry(
        [
            _module(
                "alpha",
                tools=[
                    ToolSpec("alpha.whoami", "Qui suis-je", "read", Empty, _whoami),
                    ToolSpec("alpha.add_note", "Ajoute une note", "write", NoteIn, _add_note),
                    ToolSpec("alpha.pay", "Paie", "sensitive", NoteIn, _pay),
                ],
                specialist=_profile("alpha", _alpha, "revision_plan", actions=["alpha.add_note"]),
            ),
            _module("beta", specialist=_profile("beta", _beta_slow, "slow_answer", timeout_s=0.3)),
            _module("gamma", specialist=_profile("gamma", _gamma_leaky, "balance")),
        ]
    )
    with TestClient(create_app(registry), base_url=BASE_URL) as test_client:
        create_user_sync()
        login = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        assert test_client.post("/api/v1/auth/login", json=login).status_code == 204
        for module_id in ("alpha", "beta", "gamma"):
            response = test_client.put(f"/api/v1/modules/{module_id}", json={"enabled": True})
            assert response.status_code == 200
        yield test_client


def test_read_tool_runs_as_the_user(client: TestClient) -> None:
    response = client.post("/api/v1/tools/alpha.whoami", json={})
    assert response.status_code == 200
    me = client.get("/api/v1/auth/me").json()["id"]
    assert response.json()["result"] == {"user": me}


def test_write_tool_waits_for_confirmation_then_runs_once(client: TestClient) -> None:
    pending = client.post("/api/v1/tools/alpha.add_note", json={"arguments": {"text": "reviser"}})
    assert pending.status_code == 202
    assert executed == []
    confirmation = pending.json()["confirmation_id"]

    done = client.post(f"/api/v1/tools/confirmations/{confirmation}")
    assert done.status_code == 200
    assert done.json()["result"] == {"saved": "reviser"}
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}").status_code == 409
    assert len(executed) == 1


def test_expired_confirmation_is_refused(client: TestClient) -> None:
    pending = client.post("/api/v1/tools/alpha.add_note", json={"arguments": {"text": "x"}})
    asyncio.run(migrator_sql("UPDATE lorakus.core_tool_confirmations SET expires_at = now()"))
    assert (
        client.post(f"/api/v1/tools/confirmations/{pending.json()['confirmation_id']}").status_code
        == 409
    )
    assert executed == []


def test_sensitive_tool_needs_a_recent_proof_of_identity(client: TestClient) -> None:
    pending = client.post("/api/v1/tools/alpha.pay", json={"arguments": {"text": "loyer"}})
    assert pending.status_code == 202
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '1 hour'"
        )
    )
    url = f"/api/v1/tools/confirmations/{pending.json()['confirmation_id']}"
    assert client.post(url).status_code == 403
    assert executed == []
    asyncio.run(migrator_sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now()"))
    assert client.post(url).status_code == 200
    assert [e[0] for e in executed] == ["pay"]


def test_invalid_arguments_and_disabled_modules_are_refused(client: TestClient) -> None:
    assert (
        client.post("/api/v1/tools/alpha.add_note", json={"arguments": {"text": ""}}).status_code
        == 422
    )
    assert client.post("/api/v1/tools/alpha.nope", json={}).status_code == 422
    client.put("/api/v1/modules/alpha", json={"enabled": False})
    assert client.post("/api/v1/tools/alpha.whoami", json={}).status_code == 422
    assert client.get("/api/v1/tools").json() == []


def test_tool_calls_are_audited(client: TestClient) -> None:
    pending = client.post("/api/v1/tools/alpha.add_note", json={"arguments": {"text": "x"}})
    client.post(f"/api/v1/tools/confirmations/{pending.json()['confirmation_id']}")
    actions = [
        (e["action"], e["details"].get("tool")) for e in client.get("/api/v1/auth/audit").json()
    ]
    assert ("tools.request", "alpha.add_note") in actions
    assert ("tools.execute", "alpha.add_note") in actions


def test_two_fake_specialists_register_and_answer(client: TestClient) -> None:
    listed = {s["name"]: s["intents"] for s in client.get("/api/v1/agents").json()}
    assert listed == {"alpha": ["revision_plan"], "beta": ["slow_answer"], "gamma": ["balance"]}

    alpha = client.post("/api/v1/agents/alpha/ask", json={"intent": "revision_plan"}).json()
    assert alpha["report"]["status"] == "ok"
    assert alpha["report"]["facts"][0]["label"] == "revisions"
    beta = client.post("/api/v1/agents/beta/ask", json={"intent": "slow_answer"}).json()
    assert beta["report"]["status"] == "timeout"
    assert beta["duration_ms"] < 2000

    runs = asyncio.run(
        migrator_sql("SELECT specialist, status FROM lorakus.core_agent_runs ORDER BY created_at")
    )
    assert runs == [("alpha", "ok"), ("beta", "timeout")]


def test_report_more_sensitive_than_allowed_is_refused(client: TestClient) -> None:
    gamma = client.post("/api/v1/agents/gamma/ask", json={"intent": "balance"}).json()
    assert gamma["report"]["status"] == "error"
    assert "1200" not in str(gamma)


def test_unknown_intent_or_disabled_specialist(client: TestClient) -> None:
    assert client.post("/api/v1/agents/alpha/ask", json={"intent": "balance"}).status_code == 404
    client.put("/api/v1/modules/beta", json={"enabled": False})
    assert client.post("/api/v1/agents/beta/ask", json={"intent": "slow_answer"}).status_code == 404


def test_agent_runs_are_append_only_for_the_application(client: TestClient) -> None:
    client.post("/api/v1/agents/alpha/ask", json={"intent": "revision_plan"})
    privileges = asyncio.run(
        migrator_sql(
            "SELECT has_table_privilege('lorakus_app', 'lorakus.core_agent_runs', 'UPDATE'), "
            "has_table_privilege('lorakus_app', 'lorakus.core_agent_runs', 'DELETE')"
        )
    )
    assert privileges == [(False, False)]
