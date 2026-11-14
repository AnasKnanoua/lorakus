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
from lorakus.core.tools.runtime import ToolRuntime
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec

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


async def _note_summary(_call: ToolCall, args: NoteIn) -> str:
    return f"Ajouter la note « {args.text} »"


async def _pay_summary(_call: ToolCall, args: NoteIn) -> str:
    return f"Payer : {args.text}\x07"  # caractere de controle : retire de la carte


failures: list[str] = []


async def _ping(call: ToolCall, _args: Empty) -> dict[str, Any]:
    executed.append(("ping", call.user_id, ""))
    return {"pong": True}


async def _ping_summary(_call: ToolCall, _args: Empty) -> str:
    return "Envoyer un signal"


async def _flaky(call: ToolCall, args: NoteIn) -> dict[str, Any]:
    """Echoue tant que `failures` n'est pas vide (une erreur par appel)."""
    if failures:
        raise ToolError(failures.pop(0))
    executed.append(("flaky", call.user_id, args.text))
    await asyncio.sleep(0.2)  # laisse a un second clic le temps d'arriver
    return {"ok": True}


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
    failures.clear()
    registry = ModuleRegistry(
        [
            _module(
                "alpha",
                tools=[
                    ToolSpec("alpha.whoami", "Qui suis-je", "read", Empty, _whoami),
                    ToolSpec(
                        "alpha.add_note",
                        "Ajoute une note",
                        "write",
                        NoteIn,
                        _add_note,
                        summary=_note_summary,
                    ),
                    ToolSpec("alpha.pay", "Paie", "sensitive", NoteIn, _pay, summary=_pay_summary),
                    ToolSpec("alpha.ping", "Signal", "write", Empty, _ping, summary=_ping_summary),
                    ToolSpec(
                        "alpha.flaky",
                        "Peut echouer",
                        "write",
                        NoteIn,
                        _flaky,
                        summary=_note_summary,
                    ),
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


# ----------------------------------------------------------------- PR 38 : cartes
def _pending(client: TestClient, tool: str = "alpha.add_note", note: str = "reviser") -> str:
    response = client.post(f"/api/v1/tools/{tool}", json={"arguments": {"text": note}})
    assert response.status_code == 202
    return str(response.json()["confirmation_id"])


def test_card_text_is_written_by_the_tool_from_validated_arguments(client: TestClient) -> None:
    pending = client.post("/api/v1/tools/alpha.add_note", json={"arguments": {"text": "maths"}})
    body = pending.json()
    assert body["summary"] == "Ajouter la note « maths »"
    assert body["expires_at"] is not None
    sensitive = client.post("/api/v1/tools/alpha.pay", json={"arguments": {"text": "loyer"}})
    assert sensitive.json()["summary"] == "Payer : loyer"


def test_cancelled_action_can_no_longer_be_confirmed(client: TestClient) -> None:
    confirmation = _pending(client)
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}/cancel").status_code == 204
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}").status_code == 409
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}/cancel").status_code == 409
    assert executed == []
    actions = [e["action"] for e in client.get("/api/v1/auth/audit").json()]
    assert "tools.cancel" in actions


def test_confirmed_action_cannot_be_cancelled(client: TestClient) -> None:
    confirmation = _pending(client)
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}").status_code == 200
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}/cancel").status_code == 409


def test_a_failing_action_stays_pending_and_can_be_retried(client: TestClient) -> None:
    failures.append("Ce souvenir existe déjà.")
    confirmation = _pending(client, "alpha.flaky")
    first = client.post(f"/api/v1/tools/confirmations/{confirmation}")
    assert first.status_code == 409
    assert first.json()["detail"] == "Ce souvenir existe déjà."
    assert executed == []
    second = client.post(f"/api/v1/tools/confirmations/{confirmation}")
    assert second.status_code == 200
    assert [e[0] for e in executed] == ["flaky"]


def test_decided_actions_forget_their_arguments(client: TestClient) -> None:
    confirmed, cancelled = _pending(client, note="secret-1"), _pending(client, note="secret-2")
    client.post(f"/api/v1/tools/confirmations/{confirmed}")
    client.post(f"/api/v1/tools/confirmations/{cancelled}/cancel")
    rows = asyncio.run(migrator_sql("SELECT arguments::text FROM lorakus.core_tool_confirmations"))
    assert "secret" not in str(rows)


def test_statuses_and_two_simultaneous_confirmations(client: TestClient) -> None:
    runtime: ToolRuntime = client.app.state.tools  # type: ignore[attr-defined]
    me = client.get("/api/v1/auth/me").json()["id"]
    import uuid

    user = uuid.UUID(me)
    double = _pending(client, "alpha.flaky")
    cancelled, expired, waiting = _pending(client), _pending(client), _pending(client)
    client.post(f"/api/v1/tools/confirmations/{cancelled}/cancel")
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_tool_confirmations SET expires_at = now() WHERE id = :id",
            {"id": expired},
        )
    )

    async def twice() -> list[bool]:
        async def attempt() -> bool:
            try:
                await runtime.confirm(user, uuid.UUID(double))
            except ToolError:
                return False
            return True

        return list(await asyncio.gather(attempt(), attempt()))

    outcomes = asyncio.run(twice())
    assert sorted(outcomes) == [False, True]
    assert [e[0] for e in executed] == ["flaky"]

    statuses = asyncio.run(
        runtime.statuses(user, [uuid.UUID(x) for x in (double, cancelled, expired, waiting)])
    )
    assert [statuses[uuid.UUID(x)] for x in (double, cancelled, expired, waiting)] == [
        "confirmed",
        "cancelled",
        "expired",
        "pending",
    ]


def test_application_can_only_erase_frozen_arguments(client: TestClient) -> None:
    """Garantie de la 0006 conservee par la 0012 : en lorakus_app, changer les arguments d'une
    action en attente est refuse ; seul leur effacement passe."""
    import uuid

    from lorakus.db.database import Database
    from lorakus.settings import get_settings

    confirmation = uuid.UUID(_pending(client, note="original"))
    user = uuid.UUID(client.get("/api/v1/auth/me").json()["id"])

    async def as_app(sql: str) -> None:
        database = Database.connect(get_settings())
        try:
            async with database.transaction(user) as session:
                await session.execute(text(sql), {"id": confirmation})
        finally:
            await database.close()

    with pytest.raises(Exception, match="arguments figes"):
        asyncio.run(
            as_app(
                "UPDATE lorakus.core_tool_confirmations "
                'SET arguments = \'{"text": "pirate"}\' WHERE id = :id'
            )
        )
    with pytest.raises(Exception, match="permission denied"):
        asyncio.run(
            as_app(
                "UPDATE lorakus.core_tool_confirmations "
                "SET expires_at = now() + interval '1 day' WHERE id = :id"
            )
        )
    asyncio.run(
        as_app("UPDATE lorakus.core_tool_confirmations SET arguments = '{}' WHERE id = :id")
    )


def test_a_refused_action_without_arguments_never_runs(client: TestClient) -> None:
    """Sans argument, rien n'empeche la validation : seul le refus enregistre doit bloquer."""
    pending = client.post("/api/v1/tools/alpha.ping", json={})
    confirmation = pending.json()["confirmation_id"]
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}/cancel").status_code == 204
    assert client.post(f"/api/v1/tools/confirmations/{confirmation}").status_code == 409
    assert executed == []
