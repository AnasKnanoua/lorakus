# Les types generiques de Procrastinate ne sont pas entierement resolus par pyright strict :
# l'inference est desactivee dans ce seul fichier, qui isole la bibliotheque du reste du code.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""Implementation du port JobQueue avec Procrastinate (file dans PostgreSQL).

Seul fichier du projet qui importe Procrastinate.
"""

import asyncio
import contextlib
import uuid
from datetime import timedelta
from typing import Any, Final

import procrastinate
from procrastinate import exceptions as procrastinate_exceptions
from prometheus_client import Counter

from lorakus.core.jobs.port import JobContext, JobHandler, JobRegistry
from lorakus.db.database import Database
from lorakus.settings import Settings

USER_KEY: Final = "_lorakus_user"
MAX_ATTEMPTS: Final = 5

JOB_FAILURES = Counter("lorakus_job_failures_total", "Echecs d'execution de jobs", ["job"])


class ProcrastinateQueue:
    """File de jobs ; le worker l'execute avec run_worker()."""

    def __init__(self, settings: Settings, database: Database, registry: JobRegistry) -> None:
        conninfo = (
            settings.app_database_url()
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        self.app = procrastinate.App(
            connector=procrastinate.PsycopgConnector(conninfo=conninfo, min_size=1, max_size=4)
        )
        self._db = database
        for name, handler in registry.jobs.items():
            task = self._register(name, handler)
            cron = registry.schedules.get(name)
            if cron is not None:
                self.app.periodic(cron=cron, periodic_id=name)(task)

    def _register(self, name: str, handler: JobHandler) -> Any:
        database = self._db

        async def run(context: procrastinate.JobContext, **payload: Any) -> None:
            raw_user = payload.pop(USER_KEY, None)
            job_context = JobContext(
                name=name,
                user_id=uuid.UUID(raw_user) if raw_user else None,
                attempt=(context.job.attempts or 0) + 1,
                database=database,
            )
            try:
                await handler(job_context, payload)
            except Exception:
                JOB_FAILURES.labels(job=name).inc()
                raise

        register = self.app.task(
            name=name,
            pass_context=True,
            retry=procrastinate.RetryStrategy(max_attempts=MAX_ATTEMPTS, exponential_wait=2),
        )
        return register(run)

    async def enqueue(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        user_id: uuid.UUID | None = None,
        delay: timedelta | None = None,
        lock: str | None = None,
    ) -> bool:
        """Depose le job ; False si un job portant le meme verrou attend deja."""
        if name not in self.app.tasks:
            raise ValueError(f"job inconnu : {name}")
        arguments = dict(payload or {})
        if user_id is not None:
            arguments[USER_KEY] = str(user_id)
        options: dict[str, Any] = {}
        if delay is not None:
            options["schedule_in"] = {"seconds": int(delay.total_seconds())}
        if lock is not None:
            options["queueing_lock"] = lock
        try:
            await self.app.tasks[name].configure(**options).defer_async(**arguments)
        except procrastinate_exceptions.AlreadyEnqueued:
            return False
        return True

    async def open(self) -> None:
        await self.app.open_async()

    async def close(self) -> None:
        await self.app.close_async()

    async def run_worker(self, stop: asyncio.Event) -> None:
        """Execute les jobs jusqu'a ce que stop soit leve (arret propre)."""
        worker = asyncio.create_task(
            self.app.run_worker_async(install_signal_handlers=False, concurrency=2)
        )
        await stop.wait()
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
