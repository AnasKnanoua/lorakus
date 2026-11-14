"""Telemetrie de bout en bout (PR 40) : trace complete, et aucun contenu personnel exporte.

Une valeur unique (le « canari ») est glissee partout ou un utilisateur ecrit : adresse
e-mail et mot de passe, souvenir, recherche (chaine de requete), message du chat. Elle ne doit
apparaitre dans AUCUN span ni AUCUN journal exporte. Les exportateurs reseau sont remplaces par
des exportateurs en memoire ; tout le reste (instrumentation, nettoyage) est celui de la
production.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import cast

import pytest
from conftest import BASE_URL, wipe_identity
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lorakus.ai.catalog import Catalog
from lorakus.ai.router import ModelRouter
from lorakus.ai.testing import FakeProvider, FakeReply
from lorakus.ai.usage import UsageStore
from lorakus.api.app import create_app
from lorakus.core.identity.passwords import HASHER
from lorakus.observability.logging import configure_logging
from lorakus.observability.telemetry import (
    Telemetry,
    configure_telemetry,
    instrument_app,
    instrument_database,
)

pytestmark = pytest.mark.integration

CANARY = "canari7f3k9q"
EMAIL = f"{CANARY}@example.com"
PASSWORD = f"mot de passe {CANARY} assez long"
SPANS = InMemorySpanExporter()
LOGS = InMemoryLogRecordExporter()


@pytest.fixture(scope="module")
def telemetry() -> Iterator[Telemetry]:
    # Comme create_app et le worker : journaux configures d'abord, meme formateur pour Loki.
    formatter = configure_logging(log_format="json")
    installed = configure_telemetry(
        service_name="lorakus-api",
        version="test",
        environment="test",
        traces_endpoint="",
        logs_endpoint="",
        span_exporter=SPANS,
        log_exporter=LOGS,
        log_formatter=formatter,
    )
    assert installed is not None
    yield installed
    installed.shutdown()


@pytest.fixture
def client(telemetry: Telemetry) -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    app = create_app()  # reconfigure les journaux : rebrancher la copie vers « Loki »
    telemetry.attach_logging()
    instrument_app(app)
    with TestClient(app, base_url=BASE_URL) as test_client:
        instrument_database(cast(FastAPI, test_client.app).state.database.engine)
        yield test_client


def _create_user() -> None:
    from conftest import migrator_sql

    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'owner')",
            {"id": uuid.uuid4(), "email": EMAIL, "hash": HASHER.hash(PASSWORD)},
        )
    )


def _exported(telemetry: Telemetry) -> str:
    """Tout ce qui serait parti vers Tempo et Loki, en texte."""
    telemetry.tracer_provider.force_flush()
    if telemetry.logger_provider is not None:
        telemetry.logger_provider.force_flush()
    parts: list[str] = []
    for span in SPANS.get_finished_spans():
        parts.append(span.name)
        parts.append(json.dumps(dict(span.attributes or {}), default=str))
        parts.extend(json.dumps(dict(e.attributes or {}), default=str) for e in span.events)
    for item in LOGS.get_finished_logs():
        record = item.log_record
        parts.append(str(record.body))
        parts.append(json.dumps(dict(record.attributes or {}), default=str))
    return "\n".join(parts)


def test_a_chat_reply_is_one_complete_trace_without_any_personal_content(
    client: TestClient, telemetry: Telemetry
) -> None:
    SPANS.clear()
    LOGS.clear()
    _create_user()
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 204
    assert client.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
    created = client.post(
        "/api/v1/memory/facts", json={"content": f"Aime le {CANARY}", "category": "other"}
    )
    assert created.status_code == 201
    assert client.get("/api/v1/memory/search", params={"q": CANARY}).status_code == 200

    app = cast(FastAPI, client.app)
    provider = FakeProvider(
        replies=[
            FakeReply(
                "Je regarde.", tool_calls=(("assistant__search_memory", {"question": CANARY}),)
            ),
            f"Tu aimes le {CANARY}.",
        ]
    )
    app.state.ai = ModelRouter(
        Catalog.load(),
        {"fake": provider},
        UsageStore(app.state.database),
        monthly_budget_usd=Decimal(3),
    )
    conversation = client.post("/api/v1/assistant/conversations").json()["id"]
    with client.stream(
        "POST",
        f"/api/v1/assistant/conversations/{conversation}/messages",
        json={"content": f"Qu'est-ce que j'aime ? {CANARY}"},
    ) as response:
        body = "".join(response.iter_text())
    done = next(b for b in body.strip().split("\n\n") if b.startswith("event: done"))
    reply_id = json.loads(done.split("\n")[1].removeprefix("data: "))["message_id"]

    exported = _exported(telemetry)
    assert CANARY not in exported  # ni e-mail, ni souvenir, ni recherche, ni message

    # La reponse est UNE trace : requete HTTP, preparation, appels au modele, outil, SQL.
    reply_span = next(
        s
        for s in SPANS.get_finished_spans()
        if s.name == "assistant.prepare"
        and (s.attributes or {}).get("lorakus.reply_id") == reply_id
    )
    assert reply_span.context is not None
    trace_id = reply_span.context.trace_id
    spans = [s for s in SPANS.get_finished_spans() if s.context and s.context.trace_id == trace_id]
    names = {s.name for s in spans}
    # Pas un span par morceau de la reponse en flux (etapes ASGI « send » exclues).
    assert not [n for n in names if n.endswith(("http send", "http receive"))]
    assert {"assistant.prepare", "assistant.reply", "ai.call", "tool.call"} <= names
    assert any(n.startswith("POST /api/v1/assistant/conversations") for n in names)
    assert any(n.split()[0] in ("SELECT", "INSERT", "UPDATE") for n in names)  # SQL
    calls = [s for s in spans if s.name == "ai.call"]
    assert len(calls) == 2 and all(
        (s.attributes or {})["lorakus.ai.outcome"] == "ok" for s in calls
    )

    # « Pourquoi ? » donne le meme identifiant, et des journaux portent cette trace.
    hex_id = format(trace_id, "032x")
    why = client.get(f"/api/v1/assistant/conversations/{conversation}/messages/{reply_id}/trace")
    assert why.json()["otel_trace_id"] == hex_id
    traced_logs = [
        item for item in LOGS.get_finished_logs() if item.log_record.trace_id == trace_id
    ]
    assert traced_logs, "aucun journal relie a la trace"
    assert any(hex_id in str(item.log_record.body) for item in traced_logs)
    # Loki recoit la ligne JSON de la sortie standard, telle quelle (pas un dict recopie).
    for item in traced_logs:
        line = json.loads(str(item.log_record.body))
        assert isinstance(line["event"], str) and not line["event"].startswith("{")
        assert line["trace_id"] == hex_id
        assert not {"_logger", "_name"} & set(dict(item.log_record.attributes or {}))


def test_health_checks_are_not_traced(client: TestClient, telemetry: Telemetry) -> None:
    SPANS.clear()
    assert client.get("/api/health/ready").status_code == 200
    telemetry.tracer_provider.force_flush()
    assert not [s for s in SPANS.get_finished_spans() if "health" in s.name]
