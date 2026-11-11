"""Outbox : publication transactionnelle, livraison au moins une fois, isolation."""

import uuid

import pytest
from conftest import migrator_sql
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.events import relay as relay_module
from lorakus.core.events.bus import Event, EventBus, publish
from lorakus.core.events.relay import OutboxRelay
from lorakus.core.identity.service import IdentityService
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
PASSWORD = "mot de passe de test assez long"


async def _user(identity: IdentityService) -> uuid.UUID:
    return await identity.create_owner("a@example.com", PASSWORD)


async def _publish(db: Database, user: uuid.UUID | None, kind: str = "test.happened") -> None:
    async with db.transaction(user) as session:
        await publish(session, kind, {"thing_id": "42"}, user_id=user)


async def _outbox() -> list[tuple[object, ...]]:
    return await migrator_sql(
        "SELECT event_type, attempts, published_at IS NOT NULL, dead_at IS NOT NULL "
        "FROM lorakus.core_outbox ORDER BY id"
    )


async def test_event_exists_only_if_its_transaction_commits(
    database: Database, identity: IdentityService
) -> None:
    user = await _user(identity)
    with pytest.raises(RuntimeError):
        async with database.transaction(user) as session:
            await publish(session, "test.happened", {"thing_id": "1"}, user_id=user)
            raise RuntimeError("le changement echoue")
    assert await _outbox() == []
    await _publish(database, user)
    assert await _outbox() == [("test.happened", 0, False, False)]


async def test_cannot_publish_for_another_user_nor_touch_the_queue(
    database: Database, identity: IdentityService
) -> None:
    user = await _user(identity)
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with database.transaction(user) as session:
            await publish(session, "test.happened", user_id=uuid.uuid4())
    for statement in (
        "UPDATE lorakus.core_outbox SET attempts = 0",
        "DELETE FROM lorakus.core_outbox",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with database.transaction(user) as session:
                await session.execute(text(statement))


async def test_invalid_event_types_are_refused(database: Database) -> None:
    async with database.transaction() as session:
        for bad in ("pas_de_point", "Majuscule.x", "a.b"):
            with pytest.raises(ValueError, match="invalide"):
                await publish(session, bad, user_id=None)


async def test_handlers_run_as_the_event_user_then_the_event_is_published(
    database: Database, identity: IdentityService
) -> None:
    user = await _user(identity)
    seen: list[tuple[uuid.UUID | None, object, dict[str, object]]] = []

    async def handler(event: Event, session: AsyncSession) -> None:
        current = await session.scalar(text("SELECT lorakus.current_user_id()"))
        seen.append((event.user_id, current, event.payload))

    bus = EventBus()
    bus.subscribe("test.happened", handler, "test.handler")
    await _publish(database, user)

    stats = await OutboxRelay(database, bus).run_once()

    assert stats.delivered == 1
    assert seen == [(user, user, {"thing_id": "42"})]
    assert await _outbox() == [("test.happened", 0, True, False)]
    assert (await OutboxRelay(database, bus).run_once()).delivered == 0


async def test_a_failing_handler_is_retried_without_replaying_the_others(
    database: Database, identity: IdentityService
) -> None:
    user = await _user(identity)
    calls = {"good": 0, "flaky": 0}

    async def good(_event: Event, _session: AsyncSession) -> None:
        calls["good"] += 1

    async def flaky(_event: Event, _session: AsyncSession) -> None:
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise ConnectionError("service externe indisponible")

    bus = EventBus()
    bus.subscribe("test.happened", good, "a.good")
    bus.subscribe("test.happened", flaky, "b.flaky")
    await _publish(database, user)
    relay = OutboxRelay(database, bus)

    assert (await relay.run_once()).failed == 1
    [(_, attempts, published, _)] = await _outbox()
    assert (attempts, published) == (1, False)
    # Retry immediat pour le test (en vrai : attente croissante).
    await migrator_sql("UPDATE lorakus.core_outbox SET next_attempt_at = now()")
    assert (await relay.run_once()).delivered == 1
    assert calls == {"good": 1, "flaky": 2}


async def test_event_is_set_aside_after_too_many_failures(
    database: Database, identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _user(identity)
    monkeypatch.setattr(relay_module, "MAX_ATTEMPTS", 2)

    async def broken(_event: Event, _session: AsyncSession) -> None:
        raise ValueError("toujours en panne")

    bus = EventBus()
    bus.subscribe("test.happened", broken, "broken")
    await _publish(database, user)
    relay = OutboxRelay(database, bus)
    for _ in range(2):
        await relay.run_once()
        await migrator_sql("UPDATE lorakus.core_outbox SET next_attempt_at = now()")

    assert await _outbox() == [("test.happened", 2, False, True)]
    await relay.refresh_metrics()
    assert relay_module.OUTBOX_DEAD._value.get() == 1  # type: ignore[attr-defined]
    [(error,)] = await migrator_sql("SELECT last_error FROM lorakus.core_outbox")
    assert "broken: ValueError" in str(error)


async def test_users_read_only_their_events(database: Database, identity: IdentityService) -> None:
    user = await _user(identity)
    await _publish(database, user)
    await _publish(database, None, "test.system")
    async with database.transaction(user) as session:
        kinds = (
            (await session.execute(text("SELECT event_type FROM lorakus.core_outbox")))
            .scalars()
            .all()
        )
    assert kinds == ["test.happened"]


def test_a_handler_cannot_subscribe_twice() -> None:
    bus = EventBus()

    async def handler(_event: Event, _session: AsyncSession) -> None:
        return None

    bus.subscribe("test.happened", handler, "x")
    with pytest.raises(ValueError, match="deja abonne"):
        bus.subscribe("test.happened", handler, "x")
