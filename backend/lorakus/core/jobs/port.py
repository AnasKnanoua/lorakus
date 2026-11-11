"""Jobs differes et periodiques : le port que voient les modules (ADR 0004).

    @job("academic.recompute_plan")
    async def recompute(ctx: JobContext, payload: dict[str, Any]) -> None:
        async with ctx.transaction() as session: ...

    @periodic("news.collect", cron="*/30 * * * *")
    async def collect(ctx: JobContext, payload: dict[str, Any]) -> None: ...

    await queue.enqueue("academic.recompute_plan", {"course_id": "..."}, user_id=user.id)

Les modules n'importent jamais Procrastinate (verifie par import-linter).
"""

import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.db.database import Database

JOB_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$")


@dataclass(frozen=True)
class JobContext:
    """Contexte d'execution d'un job."""

    name: str
    user_id: uuid.UUID | None
    attempt: int
    database: Database

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        """Transaction liee a l'utilisateur du job (RLS), ou sans utilisateur."""
        async with self.database.transaction(self.user_id) as session:
            yield session


JobHandler = Callable[[JobContext, dict[str, Any]], Awaitable[None]]


@dataclass
class JobRegistry:
    """Jobs connus du processus, enregistres a l'import des modules."""

    jobs: dict[str, JobHandler] = field(default_factory=dict[str, JobHandler])
    schedules: dict[str, str] = field(default_factory=dict[str, str])

    def add(self, name: str, handler: JobHandler, cron: str | None = None) -> None:
        if not JOB_NAME.fullmatch(name):
            raise ValueError(f"nom de job invalide : {name} (forme module.nom)")
        if name in self.jobs:
            raise ValueError(f"job declare deux fois : {name}")
        self.jobs[name] = handler
        if cron is not None:
            self.schedules[name] = cron


registry: Final = JobRegistry()


def job(name: str) -> Callable[[JobHandler], JobHandler]:
    """Decorateur : declare un job differe."""

    def decorator(handler: JobHandler) -> JobHandler:
        registry.add(name, handler)
        return handler

    return decorator


def periodic(name: str, *, cron: str) -> Callable[[JobHandler], JobHandler]:
    """Decorateur : declare un job lance selon une expression cron (heure UTC)."""

    def decorator(handler: JobHandler) -> JobHandler:
        registry.add(name, handler, cron)
        return handler

    return decorator


class JobQueue(Protocol):
    """Depot de jobs. La charge utile ne contient que des identifiants."""

    async def enqueue(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        user_id: uuid.UUID | None = None,
        delay: timedelta | None = None,
        lock: str | None = None,
    ) -> bool:
        """True si le job est depose ; False si un job portant le meme `lock` attend deja."""
        ...
