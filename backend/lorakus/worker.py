"""Processus worker : jobs (Procrastinate) et livraison des evenements (outbox).

    python -m lorakus.worker

Meme image que l'API, autre commande (service `worker` de compose.yml). Expose ses
metriques sur LORAKUS_METRICS_PORT ; son test de sante lit un battement de coeur mis a
jour a chaque tour de boucle (un worker bloque est donc vu, pas seulement un worker mort).
"""

import asyncio
import signal
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Final

import structlog
from prometheus_client import Gauge

from lorakus.core.events.bus import bus
from lorakus.core.events.relay import OutboxRelay
from lorakus.core.jobs.port import registry as job_registry
from lorakus.core.jobs.procrastinate_queue import ProcrastinateQueue
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.db.database import Database
from lorakus.observability.logging import configure_logging
from lorakus.observability.metrics import start_metrics_server
from lorakus.observability.telemetry import configure_telemetry, instrument_database
from lorakus.settings import get_settings

# Fichier touche a chaque tour : le test de sante du conteneur verifie son age.
HEARTBEAT_FILE: Final = Path("/tmp/lorakus-worker-heartbeat")  # noqa: S108 (tmpfs du conteneur)
HEARTBEAT_MAX_AGE_S: Final = 60

HEARTBEAT = Gauge("lorakus_worker_heartbeat_timestamp_seconds", "Dernier tour de boucle du worker")
log = structlog.get_logger("lorakus.worker")


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        HEARTBEAT.set_to_current_time()
        HEARTBEAT_FILE.touch()
        try:
            await asyncio.wait_for(stop.wait(), 10)
        except TimeoutError:
            continue


async def run() -> None:
    settings = get_settings()
    formatter = configure_logging(log_format=settings.log_format, level=settings.log_level)
    telemetry = configure_telemetry(
        service_name="lorakus-worker",
        version=version("lorakus"),
        environment=settings.environment,
        traces_endpoint=settings.otel_traces_endpoint,
        logs_endpoint=settings.otel_logs_endpoint,
        log_formatter=formatter,
    )
    if settings.metrics_port is not None:
        start_metrics_server(settings.metrics_port)
    # Importer les manifestes enregistre les handlers (@on) et les jobs (@job) des modules.
    modules = ModuleRegistry.from_entry_points()
    database = Database.connect(settings)
    if telemetry is not None:
        instrument_database(database.engine)
    queue = ProcrastinateQueue(settings, database, job_registry)
    relay = OutboxRelay(database, bus)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    await queue.open()
    log.info("worker_started", modules=len(modules), jobs=len(job_registry.jobs))
    try:
        await asyncio.gather(queue.run_worker(stop), relay.run_forever(stop), _heartbeat(stop))
    finally:
        await queue.close()
        await database.close()
        log.info("worker_stopped")
        if telemetry is not None:
            telemetry.shutdown()


def healthy() -> bool:
    """Test de sante du conteneur : battement de coeur recent."""
    try:
        return time.time() - HEARTBEAT_FILE.stat().st_mtime < HEARTBEAT_MAX_AGE_S
    except FileNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["healthcheck"]:
        return 0 if healthy() else 1
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
