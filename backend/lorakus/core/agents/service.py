"""Registre et appel des specialistes, avec trace en ajout seul (ADR 0026).

L'orchestrateur (questions multi-specialistes, disjoncteur, cache) arrive en P3 ; ici, un
specialiste est appele seul, avec son delai, et chaque appel est trace.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import insert

from lorakus.core.agents.contract import (
    SpecialistContext,
    SpecialistProfile,
    SpecialistReport,
    SpecialistRequest,
)
from lorakus.core.agents.models import AgentRun
from lorakus.core.modules.service import ModuleService
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.agents")


class AgentError(Exception):
    """Specialiste inconnu, desactive, ou intention qu'il ne traite pas."""


@dataclass(frozen=True)
class Answer:
    specialist: str
    report: SpecialistReport
    duration_ms: int


class AgentService:
    def __init__(self, database: Database, modules: ModuleService) -> None:
        self._db = database
        self._modules = modules
        self._profiles: dict[str, SpecialistProfile] = {
            m.id: m.specialist for m in modules.registry if m.specialist is not None
        }

    async def available(self, user_id: uuid.UUID) -> list[SpecialistProfile]:
        enabled = {s.manifest.id for s in await self._modules.states(user_id) if s.enabled}
        return [p for name, p in self._profiles.items() if name in enabled]

    async def ask(
        self, user_id: uuid.UUID, name: str, intent: str, params: dict[str, Any] | None = None
    ) -> Answer:
        profile = self._profiles.get(name)
        if profile is None or not await self._modules.is_enabled(user_id, name):
            raise AgentError(f"specialiste indisponible : {name}")
        if intent not in profile.intents:
            raise AgentError(f"'{name}' ne traite pas l'intention '{intent}'")
        request = SpecialistRequest(
            id=uuid.uuid4(),
            user_id=user_id,
            intent=intent,
            params=params or {},
            deadline=datetime.now(UTC) + timedelta(seconds=profile.timeout_s),
        )
        context = SpecialistContext(
            request=request, open_transaction=lambda: self._db.transaction(user_id)
        )
        started = time.monotonic()
        try:
            report = await asyncio.wait_for(profile.handler(context), profile.timeout_s)
            if report.exceeds(profile.max_report_class):
                log.warning("specialist_report_too_sensitive", specialist=name)
                report = SpecialistReport(
                    status="error", summary="Rapport refuse : donnees trop sensibles."
                )
        except TimeoutError:
            report = SpecialistReport(status="timeout", summary="Pas de reponse dans le delai.")
        except Exception as error:  # un specialiste en panne ne fait pas tomber la question
            log.warning("specialist_failed", specialist=name, error=type(error).__name__)
            report = SpecialistReport(status="error", summary="Le specialiste a echoue.")
        duration_ms = int((time.monotonic() - started) * 1000)
        async with self._db.transaction(user_id) as session:
            await session.execute(
                insert(AgentRun).values(
                    id=request.id,
                    user_id=user_id,
                    specialist=name,
                    intent=intent,
                    status=report.status,
                    duration_ms=duration_ms,
                    cost_eur=report.cost_eur,
                )
            )
        return Answer(name, report, duration_ms)
