"""Jobs : port JobQueue, implementation Procrastinate, contexte utilisateur."""

import uuid
from typing import Any

import pytest
from conftest import migrator_sql
from sqlalchemy import text

from lorakus.core.identity.service import IdentityService
from lorakus.core.jobs import procrastinate_queue as queue_module
from lorakus.core.jobs.port import JobContext, JobRegistry
from lorakus.core.jobs.procrastinate_queue import ProcrastinateQueue
from lorakus.db.database import Database
from lorakus.settings import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def test_registry_rules() -> None:
    registry = JobRegistry()

    async def handler(_ctx: JobContext, _payload: dict[str, Any]) -> None:
        return None

    registry.add("demo.do_it", handler)
    for bad in ("sans_point", "Demo.x"):
        with pytest.raises(ValueError, match="invalide"):
            registry.add(bad, handler)
    with pytest.raises(ValueError, match="deux fois"):
        registry.add("demo.do_it", handler)


async def _run_pending(queue: ProcrastinateQueue) -> None:
    await queue.app.run_worker_async(wait=False, install_signal_handlers=False)


async def test_job_runs_with_its_payload_as_its_user(
    database: Database, identity: IdentityService
) -> None:
    user = await identity.create_owner("a@example.com", "mot de passe assez long")
    seen: list[tuple[str, uuid.UUID | None, object, dict[str, Any], int]] = []

    async def handler(ctx: JobContext, payload: dict[str, Any]) -> None:
        async with ctx.transaction() as session:
            current = await session.scalar(text("SELECT lorakus.current_user_id()"))
        seen.append((ctx.name, ctx.user_id, current, payload, ctx.attempt))

    registry = JobRegistry()
    registry.add("demo.compute", handler)
    queue = ProcrastinateQueue(get_settings(), database, registry)
    await queue.open()
    try:
        assert await queue.enqueue("demo.compute", {"item_id": "7"}, user_id=user)
        await _run_pending(queue)
    finally:
        await queue.close()

    assert seen == [("demo.compute", user, user, {"item_id": "7"}, 1)]


async def test_lock_prevents_duplicates_and_unknown_jobs_are_refused(database: Database) -> None:
    async def handler(_ctx: JobContext, _payload: dict[str, Any]) -> None:
        return None

    registry = JobRegistry()
    registry.add("demo.sync", handler)
    queue = ProcrastinateQueue(get_settings(), database, registry)
    await queue.open()
    try:
        assert await queue.enqueue("demo.sync", lock="sync:1")
        assert not await queue.enqueue("demo.sync", lock="sync:1")
        with pytest.raises(ValueError, match="inconnu"):
            await queue.enqueue("demo.nope")
    finally:
        await queue.close()


async def test_failures_are_counted_and_retried(database: Database) -> None:
    async def broken(_ctx: JobContext, _payload: dict[str, Any]) -> None:
        raise ConnectionError("indisponible")

    registry = JobRegistry()
    registry.add("demo.broken", broken)
    queue = ProcrastinateQueue(get_settings(), database, registry)
    before = queue_module.JOB_FAILURES.labels(job="demo.broken")._value.get()  # type: ignore[attr-defined]
    await queue.open()
    try:
        await queue.enqueue("demo.broken")
        await _run_pending(queue)
    finally:
        await queue.close()
    after = queue_module.JOB_FAILURES.labels(job="demo.broken")._value.get()  # type: ignore[attr-defined]
    assert after == before + 1
    # Echec retente plus tard (attente exponentielle), pas abandonne.
    assert await migrator_sql("SELECT status, attempts FROM lorakus.procrastinate_jobs") == [
        ("todo", 1)
    ]
