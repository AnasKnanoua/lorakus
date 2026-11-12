"""Journal de consommation IA sur PostgreSQL, en role lorakus_app (RLS active)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from conftest import migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from lorakus.ai.catalog import Catalog
from lorakus.ai.port import ChatMessage, ChatRequest, Usage
from lorakus.ai.router import AIUnavailableError, ChatResult, ModelRouter
from lorakus.ai.testing import FakeProvider
from lorakus.ai.usage import UsageStore, month_start
from lorakus.api.app import create_app
from lorakus.core.identity.service import IdentityService
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"
USAGE = Usage(input_tokens=3000, output_tokens=400)


async def _two_users(identity: IdentityService) -> tuple[uuid.UUID, uuid.UUID]:
    first = await identity.create_owner("a@example.com", PASSWORD)
    second = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": second},
    )
    return first, second


async def _record(store: UsageStore, user: uuid.UUID, cost: str) -> None:
    await store.record(
        user,
        task="chat",
        provider="anthropic",
        model="claude-haiku-5-5",
        data_class="personal",
        usage=USAGE,
        cost_usd=Decimal(cost),
        duration_ms=850,
    )


async def test_month_cost_sums_only_the_current_users_spending(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)
    store = UsageStore(database)
    await _record(store, first, "0.0005")
    await _record(store, first, "0.0012")
    await _record(store, second, "1.5")

    assert await store.month_cost(first) == Decimal("0.0017")
    assert await store.month_cost(second) == Decimal("1.5")


async def test_users_only_see_their_own_usage_rows(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)
    store = UsageStore(database)
    await _record(store, second, "1")

    async with database.transaction(first) as session:
        visible = await session.scalar(text("SELECT count(*) FROM lorakus.core_ai_usage"))

    assert visible == 0


async def test_usage_cannot_be_recorded_for_another_user(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with database.transaction(first) as session:
            await session.execute(
                text(
                    "INSERT INTO lorakus.core_ai_usage (id, user_id, task, provider, model, "
                    "data_class, input_tokens, output_tokens, cache_read_tokens, "
                    "cache_write_tokens, cost_usd, duration_ms) VALUES (:id, :owner, 'chat', "
                    "'anthropic', 'm', 'personal', 1, 1, 0, 0, 0, 1)"
                ),
                {"id": uuid.uuid4(), "owner": second},
            )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE lorakus.core_ai_usage SET cost_usd = 0",
        "DELETE FROM lorakus.core_ai_usage",
        "TRUNCATE lorakus.core_ai_usage",
    ],
)
async def test_spending_cannot_be_erased_by_the_application(
    database: Database, identity: IdentityService, statement: str
) -> None:
    first, _ = await _two_users(identity)
    await _record(UsageStore(database), first, "2")

    with pytest.raises(ProgrammingError, match="permission denied"):
        async with database.transaction(first) as session:
            await session.execute(text(statement))

    assert await UsageStore(database).month_cost(first) == Decimal("2")


async def test_budget_restarts_on_the_first_of_the_month(
    database: Database, identity: IdentityService
) -> None:
    first, _ = await _two_users(identity)
    await _record(UsageStore(database), first, "2")
    next_month = month_start(datetime.now(UTC)) + timedelta(days=32)  # dans le mois suivant

    later = UsageStore(database, clock=lambda: next_month)

    assert await later.month_cost(first) == Decimal("0")


def test_month_start_is_midnight_utc_on_the_first() -> None:
    assert month_start(datetime(2026, 11, 12, 15, 30, tzinfo=UTC)) == datetime(
        2026, 11, 1, tzinfo=UTC
    )


async def test_router_stops_once_recorded_spending_reaches_the_budget(
    database: Database, identity: IdentityService
) -> None:
    first, _ = await _two_users(identity)
    provider = FakeProvider(replies=["une reponse assez longue pour couter quelque chose"])
    router = ModelRouter(
        Catalog.load(),
        {"fake": provider},
        UsageStore(database),
        monthly_budget_usd=Decimal("0.001"),
    )
    request = ChatRequest(
        system="Tu es Lorakus.", messages=[ChatMessage(role="user", content="Salut")]
    )

    events = [
        e
        async for e in router.chat_stream(
            first, task="chat", data_class="personal", request=request
        )
    ]
    assert isinstance(events[-1], ChatResult)
    # Le faux fournisseur ne coute rien : on simule une depense reelle au-dela du plafond.
    await _record(UsageStore(database), first, "0.002")

    with pytest.raises(AIUnavailableError) as unavailable:
        _ = [
            e
            async for e in router.chat_stream(
                first, task="chat", data_class="personal", request=request
            )
        ]

    assert unavailable.value.reason == "budget"
    assert len(provider.calls) == 1
    rows = await migrator_sql(
        "SELECT provider, model, data_class FROM lorakus.core_ai_usage WHERE task = 'chat' "
        "AND provider = 'fake'"
    )
    assert rows == [("fake", "echo", "personal")]


def test_application_starts_with_the_ai_router(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    assert isinstance(app.state.ai, ModelRouter)


def test_invalid_ai_configuration_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from lorakus.ai import catalog

    def broken() -> Catalog:
        raise catalog.CatalogError("configuration IA invalide : test")

    monkeypatch.setattr(catalog.Catalog, "load", broken)

    with pytest.raises(catalog.CatalogError):
        create_app()
