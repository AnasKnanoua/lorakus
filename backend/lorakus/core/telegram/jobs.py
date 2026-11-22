"""Job du bot Telegram (P5, PR 54) : un seul releve pour tous les utilisateurs.

Chaque minute, `telegram.poll` releve les messages pendant 45 secondes au plus (attente
longue : une reponse arrive en quelques secondes). Sans jeton (developpement, ou bot pas
encore configure) : rien. Importe par le worker, qui l'enregistre a son demarrage.
"""

from datetime import UTC, datetime
from functools import cache
from typing import Any

import structlog

from lorakus.core.jobs.port import JobContext, periodic
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.telegram.inbox import CONFIGURED, PollState, poll_round
from lorakus.core.telegram.setup import bot

log = structlog.get_logger("lorakus.telegram")

STATE = PollState()


@cache
def registry() -> ModuleRegistry:
    return ModuleRegistry.from_entry_points()


@periodic("telegram.poll", cron="* * * * *")
async def poll(ctx: JobContext, payload: dict[str, Any]) -> None:
    current = bot()
    CONFIGURED.set(0 if current is None else 1)  # l'alerte de releve arretee ne vaut qu'avec un bot
    if current is None:
        return
    counts = await poll_round(ctx.database, current, registry(), STATE, lambda: datetime.now(UTC))
    if counts:
        log.info("telegram_poll_round", **counts)
