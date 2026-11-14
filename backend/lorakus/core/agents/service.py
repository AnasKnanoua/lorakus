"""Registre et appel des specialistes, avec trace en ajout seul (ADR 0026).

Ici, un specialiste est appele seul, avec son delai, et chaque appel est trace.
L'orchestrateur (orchestrator.py, PR 39) en appelle plusieurs en parallele, avec disjoncteur
et cache ; il passe trace_id (la reponse du chat) et for_llm (le rapport ira au modele).
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import structlog
from sqlalchemy import insert

from lorakus.core.agents.contract import (
    DataClass,
    SpecialistContext,
    SpecialistProfile,
    SpecialistReport,
    SpecialistRequest,
)
from lorakus.core.agents.models import AgentRun
from lorakus.core.modules.service import ModuleService
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.agents")


_RANK: Final[dict[str, int]] = {"public": 0, "personal": 1, "sensitive": 2}


def llm_eligible(profile: SpecialistProfile) -> bool:
    """Le rapport de ce specialiste peut-il aller au modele (fournisseur externe) ?

    Non si sa classe maximale est `sensitive` : son resume pourrait en contenir, et le
    filtre par marqueurs (ADR 0027) n'arrive qu'en P10. Ses faits ne passent jamais non plus.
    """
    return _RANK[profile.max_report_class] < _RANK["sensitive"]


def classes_for_llm(profile: SpecialistProfile, report: SpecialistReport) -> list[DataClass]:
    """Classes de donnees du rapport qui iront au modele (trace, ADR 0026)."""
    if not llm_eligible(profile) or report.status not in ("ok", "partial"):
        return []
    classes: set[DataClass] = {profile.max_report_class}
    classes.update(f.data_class for f in report.facts if _RANK[f.data_class] < _RANK["sensitive"])
    return sorted(classes, key=lambda c: _RANK[c])


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

    def profile(self, name: str) -> SpecialistProfile | None:
        return self._profiles.get(name)

    async def ask(
        self,
        user_id: uuid.UUID,
        name: str,
        intent: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_s: float | None = None,
        trace_id: str | None = None,
        for_llm: bool = False,
    ) -> Answer:
        """Appelle un specialiste. timeout_s : delai impose (au plus celui du profil)."""
        profile = self._profiles.get(name)
        if profile is None or not await self._modules.is_enabled(user_id, name):
            raise AgentError(f"specialiste indisponible : {name}")
        if intent not in profile.intents:
            raise AgentError(f"'{name}' ne traite pas l'intention '{intent}'")
        delay = min(profile.timeout_s, timeout_s) if timeout_s is not None else profile.timeout_s
        request = SpecialistRequest(
            id=uuid.uuid4(),
            user_id=user_id,
            intent=intent,
            params=params or {},
            deadline=datetime.now(UTC) + timedelta(seconds=delay),
        )
        context = SpecialistContext(
            request=request, open_transaction=lambda: self._db.transaction(user_id)
        )
        started = time.monotonic()
        try:
            report = await asyncio.wait_for(profile.handler(context), max(delay, 0.001))
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
                    data_classes_sent=classes_for_llm(profile, report) if for_llm else [],
                    trace_id=trace_id,
                )
            )
        return Answer(name, report, duration_ms)
