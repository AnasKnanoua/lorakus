"""Livraison des evenements de l'outbox, par le worker."""

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import structlog
from prometheus_client import Counter, Gauge
from sqlalchemy import text

from lorakus.core.events.bus import Event, EventBus
from lorakus.db.database import Database

MAX_ATTEMPTS: Final = 8
BATCH: Final = 50
LEASE: Final = timedelta(minutes=2)

log = structlog.get_logger("lorakus.events")

OUTBOX_PENDING = Gauge("lorakus_outbox_pending", "Evenements en attente de livraison")
OUTBOX_OLDEST = Gauge(
    "lorakus_outbox_oldest_pending_seconds", "Age de l'evenement en attente le plus ancien"
)
OUTBOX_DEAD = Gauge("lorakus_outbox_dead", "Evenements abandonnes apres trop d'echecs")
HANDLER_FAILURES = Counter(
    "lorakus_event_handler_failures_total", "Echecs de handlers d'evenements", ["event_type"]
)


@dataclass(frozen=True)
class RelayStats:
    delivered: int
    failed: int


class OutboxRelay:
    """Reclame un lot d'evenements, les livre, enregistre le resultat."""

    def __init__(self, database: Database, bus: EventBus) -> None:
        self._db = database
        self._bus = bus

    async def run_once(self) -> RelayStats:
        async with self._db.transaction() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, user_id, event_type, payload, attempts "
                        "FROM lorakus.outbox_claim(:limit, :lease)"
                    ),
                    {"limit": BATCH, "lease": LEASE},
                )
            ).all()
        delivered = failed = 0
        for row in rows:
            event = Event(row.id, row.event_type, row.user_id, dict(row.payload), row.attempts + 1)
            if await self._deliver(event):
                delivered += 1
            else:
                failed += 1
        return RelayStats(delivered, failed)

    async def _deliver(self, event: Event) -> bool:
        async with self._db.transaction() as session:
            done = set(
                (
                    await session.execute(
                        text("SELECT lorakus.outbox_done_handlers(:id)"), {"id": event.id}
                    )
                ).scalars()
            )
        for name, handler in self._bus.handlers_for(event.type).items():
            if name in done:
                continue
            try:
                # Le handler et la trace de sa reussite sont dans la MEME transaction :
                # soit les deux sont ecrits, soit aucun (pas de double execution).
                async with self._db.transaction(event.user_id) as session:
                    await handler(event, session)
                    await session.execute(
                        text("SELECT lorakus.outbox_handler_done(:id, :name)"),
                        {"id": event.id, "name": name},
                    )
            except Exception as error:  # un handler en panne ne bloque pas les autres
                HANDLER_FAILURES.labels(event_type=event.type).inc()
                log.warning(
                    "event_handler_failed",
                    event_id=event.id,
                    event_type=event.type,
                    handler=name,
                    attempt=event.attempt,
                    error=type(error).__name__,
                )
                await self._fail(event.id, f"{name}: {type(error).__name__}: {error}")
                return False
        async with self._db.transaction() as session:
            await session.execute(text("SELECT lorakus.outbox_complete(:id)"), {"id": event.id})
        return True

    async def _fail(self, event_id: int, error: str) -> None:
        async with self._db.transaction() as session:
            await session.execute(
                text("SELECT lorakus.outbox_fail(:id, :error, :max)"),
                {"id": event_id, "error": error, "max": MAX_ATTEMPTS},
            )

    async def refresh_metrics(self) -> None:
        async with self._db.transaction() as session:
            stats = (
                await session.execute(
                    text("SELECT pending, oldest_pending_seconds, dead FROM lorakus.outbox_stats()")
                )
            ).one()
        OUTBOX_PENDING.set(stats.pending)
        OUTBOX_OLDEST.set(stats.oldest_pending_seconds)
        OUTBOX_DEAD.set(stats.dead)

    async def run_forever(self, stop: asyncio.Event, idle_seconds: float = 2.0) -> None:
        """Boucle du worker : livre, met a jour les metriques, attend s'il n'y a rien."""
        while not stop.is_set():
            try:
                stats = await self.run_once()
                await self.refresh_metrics()
            except Exception:  # la base peut etre momentanement indisponible
                log.exception("outbox_relay_error")
                stats = RelayStats(0, 0)
            if stats.delivered == 0 and stats.failed == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), idle_seconds)
