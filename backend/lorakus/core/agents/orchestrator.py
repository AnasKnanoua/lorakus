"""Orchestrateur des specialistes (ADR 0026, PR 39).

Pour une question, le Majordome choisit des specialistes (routing.py), puis l'orchestrateur :

- les interroge EN PARALLELE (au plus MAX_PARALLEL), chacun avec son delai, et la question
  entiere sous un plafond global (deadline_s) : un specialiste lent est marque `timeout`
  sans retarder les autres ;
- ecarte un specialiste en panne repetee (disjoncteur : 3 echecs, 15 minutes), comme pour
  les fournisseurs d'IA : une panne ne ralentit jamais la reponse ;
- garde un rapport en cache s'il le permet (cache_ttl_s du profil), par utilisateur ;
- ne reessaie jamais en direct (ADR 0026).

Le cache et le disjoncteur vivent dans le processus de l'API (un seul aujourd'hui, comme le
disjoncteur de l'IA). L'invalidation du cache par evenements attend le premier specialiste
reel qui en a besoin : les evenements sont traites par le worker, un autre processus.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import structlog
from opentelemetry import trace

from lorakus.ai.breaker import CircuitBreaker
from lorakus.core.agents.contract import SpecialistProfile, SpecialistReport
from lorakus.core.agents.service import AgentError, Answer, classes_for_llm

log = structlog.get_logger("lorakus.agents")
_TRACER = trace.get_tracer("lorakus.agents")

MAX_PARALLEL: Final = 4
DEADLINE_S: Final = 3.0
BREAKER_THRESHOLD: Final = 3
BREAKER_COOLDOWN_S: Final = 15 * 60
CACHE_MAX_ENTRIES: Final = 1000


class SpecialistDirectory(Protocol):
    """Ce dont l'orchestrateur a besoin (AgentService en production, un faux en test)."""

    def profile(self, name: str) -> SpecialistProfile | None: ...

    async def available(self, user_id: uuid.UUID) -> list[SpecialistProfile]: ...

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
    ) -> Answer: ...


@dataclass(frozen=True)
class Target:
    """Un specialiste a interroger, avec l'intention retenue par le routage."""

    specialist: str
    intent: str
    params: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class Consultation:
    """Issue d'une consultation : le rapport, et de quoi la tracer."""

    specialist: str
    display_name: str
    intent: str
    report: SpecialistReport
    duration_ms: int
    cached: bool = False
    skipped: str | None = None  # "breaker" si le disjoncteur l'a ecarte
    data_classes: tuple[str, ...] = ()


def _key(user_id: uuid.UUID, target: Target) -> tuple[uuid.UUID, str, str, str]:
    return (
        user_id,
        target.specialist,
        target.intent,
        json.dumps(target.params, sort_keys=True, default=str),
    )


class Orchestrator:
    def __init__(
        self,
        agents: SpecialistDirectory,
        *,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._agents = agents
        self._breaker = breaker or CircuitBreaker(
            threshold=BREAKER_THRESHOLD, cooldown_s=BREAKER_COOLDOWN_S, clock=clock
        )
        self._clock = clock
        self._cache: dict[tuple[uuid.UUID, str, str, str], tuple[float, SpecialistReport]] = {}

    @property
    def agents(self) -> SpecialistDirectory:
        return self._agents

    async def consult(
        self,
        user_id: uuid.UUID,
        targets: Sequence[Target],
        *,
        trace_id: str | None = None,
        deadline_s: float = DEADLINE_S,
    ) -> list[Consultation]:
        """Interroge les specialistes en parallele ; une Consultation par cible, dans l'ordre."""
        started = self._clock()
        chosen = list(targets)[:MAX_PARALLEL]
        tasks = [self._one(user_id, target, trace_id, started, deadline_s) for target in chosen]
        return list(await asyncio.gather(*tasks))

    async def _one(
        self,
        user_id: uuid.UUID,
        target: Target,
        trace_id: str | None,
        started: float,
        deadline_s: float,
    ) -> Consultation:
        attributes = {"lorakus.specialist": target.specialist, "lorakus.intent": target.intent}
        with _TRACER.start_as_current_span("specialist.consult", attributes=attributes) as span:
            result = await self._consult_one(user_id, target, trace_id, started, deadline_s)
            span.set_attributes(
                {
                    "lorakus.specialist.status": result.report.status,
                    "lorakus.specialist.cached": result.cached,
                    "lorakus.specialist.skipped": result.skipped or "",
                }
            )
            return result

    async def _consult_one(
        self,
        user_id: uuid.UUID,
        target: Target,
        trace_id: str | None,
        started: float,
        deadline_s: float,
    ) -> Consultation:
        profile = self._agents.profile(target.specialist)
        display = profile.display_name if profile else target.specialist
        cached = self._cached(user_id, target)
        if cached is not None and profile is not None:
            classes = tuple(classes_for_llm(profile, cached))
            return Consultation(
                target.specialist, display, target.intent, cached, 0, True, None, classes
            )
        if not self._breaker.allows(target.specialist):
            report = SpecialistReport(status="error", summary="Specialiste momentanement ecarte.")
            return Consultation(
                target.specialist, display, target.intent, report, 0, False, "breaker"
            )
        remaining = max(deadline_s - (self._clock() - started), 0.001)
        try:
            answer = await self._agents.ask(
                user_id,
                target.specialist,
                target.intent,
                target.params,
                timeout_s=remaining,
                trace_id=trace_id,
                for_llm=True,
            )
        except AgentError:
            report = SpecialistReport(status="error", summary="Specialiste indisponible.")
            return Consultation(target.specialist, display, target.intent, report, 0)
        except BaseException:
            self._breaker.abandoned(target.specialist)  # client parti : aucun verdict
            raise
        report = answer.report
        if report.status in ("error", "timeout"):
            self._breaker.failure(target.specialist)
            log.info("specialist_failure", specialist=target.specialist, status=report.status)
        else:
            self._breaker.success(target.specialist)
            if profile is not None and profile.cache_ttl_s > 0:
                self._store(user_id, target, report, profile.cache_ttl_s)
        classes = tuple(classes_for_llm(profile, report)) if profile else ()
        return Consultation(
            target.specialist,
            display,
            target.intent,
            report,
            answer.duration_ms,
            False,
            None,
            classes,
        )

    def _cached(self, user_id: uuid.UUID, target: Target) -> SpecialistReport | None:
        entry = self._cache.get(_key(user_id, target))
        if entry is None:
            return None
        expires, report = entry
        if self._clock() >= expires:
            del self._cache[_key(user_id, target)]
            return None
        return report

    def _store(
        self, user_id: uuid.UUID, target: Target, report: SpecialistReport, ttl_s: float
    ) -> None:
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            now = self._clock()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                self._cache.pop(next(iter(self._cache)))  # le plus ancien
        self._cache[_key(user_id, target)] = (self._clock() + ttl_s, report)

    def forget_user(self, user_id: uuid.UUID) -> None:
        """Retire du cache tout ce qui concerne un utilisateur (ex. donnees effacees)."""
        self._cache = {k: v for k, v in self._cache.items() if k[0] != user_id}
