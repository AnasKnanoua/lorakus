"""Majordome et specialistes de bout en bout (PR 39, critere de fin de la phase 3).

Quatre specialistes factices : le Sergent (rapide), le Preparateur (rapide), un specialiste
lent (depasse son delai) et un Tresorier `sensitive` qui essaie de glisser un solde dans son
resume. Le modele est un FakeProvider : tout ce qu'il recoit est inspecte.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast

import pytest
from conftest import (
    BASE_URL,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    create_user_sync,
    migrator_sql,
    wipe_identity,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lorakus.ai.catalog import Catalog
from lorakus.ai.embeddings import FakeEmbedder
from lorakus.ai.router import ModelRouter
from lorakus.ai.testing import FakeProvider
from lorakus.ai.usage import UsageStore
from lorakus.api.app import create_app
from lorakus.core.agents.contract import (
    Confidence,
    Fact,
    SpecialistContext,
    SpecialistProfile,
    SpecialistReport,
)
from lorakus.core.agents.routing import IntentRouter
from lorakus.core.identity.passwords import HASHER
from lorakus.core.modules.manifest import ModuleManifest
from lorakus.core.modules.registry import ModuleRegistry
from lorakus_modules.assistant.manifest import manifest as assistant_manifest

pytestmark = pytest.mark.integration
BASE = "/api/v1/assistant"
SECRET = "1200"


def _ok(summary: str, facts: list[Fact] | None = None) -> SpecialistReport:
    return SpecialistReport(
        status="ok",
        summary=summary,
        facts=facts or [],
        confidence=Confidence(level=0.9, reason="donnees du jour"),
    )


async def _sergent(_ctx: SpecialistContext) -> SpecialistReport:
    await asyncio.sleep(0.3)
    fact = Fact(
        label="cours", value="3 cours", data_class="personal", source="agenda", measured=True
    )
    return _ok("Trois cours aujourd'hui, dont un TP.", [fact])


async def _preparateur(_ctx: SpecialistContext) -> SpecialistReport:
    await asyncio.sleep(0.4)
    return _ok("Nuit de 7 h, plutôt régulière.")


async def _slow(_ctx: SpecialistContext) -> SpecialistReport:
    await asyncio.sleep(10)
    return _ok("Jamais lu.")


async def _tresorier(_ctx: SpecialistContext) -> SpecialistReport:
    fact = Fact(label="solde", value=SECRET, data_class="sensitive", source="banque", measured=True)
    return _ok(f"Solde de {SECRET} euros.", [fact])


def _module(module_id: str, profile: SpecialistProfile) -> ModuleManifest:
    return ModuleManifest(
        id=module_id,
        name=module_id,
        version="0.1.0",
        requires_core=">=0.1,<1.0",
        description="Module factice",
        specialist=profile,
    )


def _profile(
    name: str, display: str, handler: Any, keyword: str, **extra: Any
) -> SpecialistProfile:
    intent = f"{name}_main"  # une intention appartient a un seul specialiste (ADR 0026)
    return SpecialistProfile(
        name=name,
        display_name=display,
        intents=[intent],
        limits="Factice.",
        handler=handler,
        keywords={intent: [keyword]},
        **extra,
    )


SPECIALISTS = [
    _module("alpha", _profile("alpha", "Sergent", _sergent, "aujourd'hui")),
    _module("beta", _profile("beta", "Préparateur", _preparateur, "dormi")),
    _module("gamma", _profile("gamma", "Lent", _slow, "lent", timeout_s=1.0)),
    _module(
        "delta", _profile("delta", "Trésorier", _tresorier, "argent", max_report_class="sensitive")
    ),
]


def use_model(client: TestClient, *replies: str) -> FakeProvider:
    app = cast(FastAPI, client.app)
    provider = FakeProvider(replies=list(replies))
    app.state.ai = ModelRouter(
        Catalog.load(),
        {"fake": provider},
        UsageStore(app.state.database),
        monthly_budget_usd=Decimal(3),
    )
    return provider


def login(client: TestClient, email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD) -> None:
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code
        == 204
    )


def enable(client: TestClient, *module_ids: str) -> None:
    for module_id in module_ids:
        assert client.put(f"/api/v1/modules/{module_id}", json={"enabled": True}).status_code == 200


def send(client: TestClient, conversation_id: str, text: str) -> str:
    """Envoie un message et renvoie l'identifiant de la reponse (evenement done)."""
    with client.stream(
        "POST", f"{BASE}/conversations/{conversation_id}/messages", json={"content": text}
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    done = next(b for b in body.strip().split("\n\n") if b.startswith("event: done"))
    return str(json.loads(done.split("\n")[1].removeprefix("data: "))["message_id"])


def sent_to_model(provider: FakeProvider) -> str:
    return "\n".join(request.model_dump_json() for _, request in provider.calls)


@pytest.fixture
def owner() -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    registry = ModuleRegistry([assistant_manifest, *SPECIALISTS])
    with TestClient(create_app(registry), base_url=BASE_URL) as client:
        create_user_sync()
        login(client)
        enable(client, "assistant")
        yield client


@pytest.fixture
def conversation(owner: TestClient) -> str:
    return str(owner.post(f"{BASE}/conversations").json()["id"])


def trace(client: TestClient, conversation_id: str, message_id: str) -> Any:
    return client.get(f"{BASE}/conversations/{conversation_id}/messages/{message_id}/trace")


# ---------------------------------------------------------------------------------
def test_multi_specialist_question_answers_in_under_5_s_with_a_full_trace(
    owner: TestClient, conversation: str
) -> None:
    enable(owner, "alpha", "beta", "gamma")
    provider = use_model(owner, "Voici ta journée.")

    started = time.monotonic()
    reply_id = send(
        owner, conversation, "Qu'est-ce que je fais aujourd'hui ? J'ai dormi ? Et le lent ?"
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    system = provider.calls[0][1].system
    assert "<rapports>" in system
    assert "[Sergent] Trois cours aujourd'hui, dont un TP." in system
    assert "cours : 3 cours (mesuré, source : agenda)" in system
    assert "[Préparateur] Nuit de 7 h, plutôt régulière." in system
    assert "Jamais lu" not in system  # le specialiste lent n'a rien donne

    explained = trace(owner, conversation, reply_id).json()
    assert explained["routing"]["tier"] == "rules"
    statuses = {s["specialist"]: s["status"] for s in explained["specialists"]}
    assert statuses == {"alpha": "ok", "beta": "ok", "gamma": "timeout"}
    assert explained["model_calls"] == 1
    assert explained["data_classes_sent"] == ["personal"]
    assert explained["prompt_version"]

    runs = asyncio.run(
        migrator_sql(
            "SELECT specialist, status, trace_id FROM lorakus.core_agent_runs ORDER BY specialist"
        )
    )
    assert runs == [
        ("alpha", "ok", reply_id),
        ("beta", "ok", reply_id),
        ("gamma", "timeout", reply_id),
    ]


def test_sensitive_values_never_reach_the_model(owner: TestClient, conversation: str) -> None:
    enable(owner, "delta")
    provider = use_model(owner, "Je ne peux pas voir ton solde.")

    reply_id = send(owner, conversation, "Il me reste combien d'argent ?")

    assert SECRET not in sent_to_model(provider)
    assert "<rapports>" not in provider.calls[0][1].system
    explained = trace(owner, conversation, reply_id).json()
    assert explained["specialists"][0]["status"] == "ok"
    assert explained["specialists"][0]["data_classes"] == []
    runs = asyncio.run(migrator_sql("SELECT data_classes_sent FROM lorakus.core_agent_runs"))
    assert runs == [([],)]


def test_without_specialists_the_chat_does_nothing_more(
    owner: TestClient, conversation: str
) -> None:
    spy = FakeEmbedder()
    cast(FastAPI, owner.app).state.intent_router = IntentRouter(spy)
    provider = use_model(owner, "Bonjour !")

    reply_id = send(owner, conversation, "Qu'est-ce que je fais aujourd'hui ?")

    assert spy.calls == []  # pas meme un embedding pour router
    assert len(provider.calls) == 1
    explained = trace(owner, conversation, reply_id).json()
    assert explained["routing"] is None and explained["specialists"] == []


def test_trace_lists_memory_by_identifier_and_forgets_deleted_facts(
    owner: TestClient, conversation: str
) -> None:
    created = owner.post(
        "/api/v1/memory/facts", json={"content": "Révise le matin", "category": "habit"}
    )
    fact_id = created.json()["id"]
    use_model(owner, "Noté.")
    reply_id = send(owner, conversation, "Quand est-ce que je révise ?")

    explained = trace(owner, conversation, reply_id).json()
    assert [f["content"] for f in explained["memory_facts"]] == ["Révise le matin"]
    stored = asyncio.run(
        migrator_sql("SELECT trace::text FROM lorakus.asst_messages WHERE trace IS NOT NULL")
    )
    assert "Révise le matin" not in str(stored)  # la trace garde l'identifiant, pas le texte

    assert owner.delete(f"/api/v1/memory/facts/{fact_id}").status_code == 204
    after = trace(owner, conversation, reply_id).json()
    assert after["memory_facts"] == [] and after["memory_facts_removed"] == 1


def test_trace_is_private_and_only_for_replies(owner: TestClient, conversation: str) -> None:
    use_model(owner, "Réponse.")
    reply_id = send(owner, conversation, "Bonjour")
    detail = owner.get(f"{BASE}/conversations/{conversation}").json()
    user_message = detail["messages"][0]["id"]
    assert trace(owner, conversation, user_message).status_code == 404
    assert trace(owner, conversation, str(uuid.uuid4())).status_code == 404

    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, 'autre@example.com', :hash, 'user')",
            {"id": uuid.uuid4(), "hash": HASHER.hash("un autre mot de passe long")},
        )
    )
    other = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    login(other, "autre@example.com", "un autre mot de passe long")
    enable(other, "assistant")
    assert trace(other, conversation, reply_id).status_code == 404


def test_replies_from_before_traces_explain_nothing(owner: TestClient, conversation: str) -> None:
    use_model(owner, "Ancienne réponse.")
    reply_id = send(owner, conversation, "Bonjour")
    asyncio.run(migrator_sql("UPDATE lorakus.asst_messages SET trace = NULL"))
    response = trace(owner, conversation, reply_id)
    assert response.status_code == 404
    assert response.json()["detail"] == "Aucune explication pour cette réponse."
