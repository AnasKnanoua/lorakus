"""Job unique de la politique d'intervention (MODULE_SYSTEM.md §11, ADR 0042).

Chaque minute, il examine les signaux dus de TOUS les utilisateurs. Aucun minuteur par
utilisateur. Importe par le worker, qui l'enregistre a son demarrage.
"""

from datetime import UTC, datetime
from functools import cache
from typing import Any

import structlog

from lorakus.core.jobs.port import JobContext, periodic
from lorakus.core.outbound import OutboundHttp
from lorakus.core.signals.dispatch import TelegramChannel, WebPusher, dispatch_due
from lorakus.core.signals.webpush import VapidKeys
from lorakus.core.telegram.setup import bot as telegram_bot
from lorakus.settings import get_settings

log = structlog.get_logger("lorakus.signals")

# Identite donnee aux services de notification (RFC 8292) : notre adresse publique.
DEFAULT_SUBJECT = "https://app.lorakus.app"


@cache
def pusher() -> WebPusher | None:
    """L'envoi reel, ou None sans cles VAPID (developpement : cartes seulement)."""
    settings = get_settings()
    private = settings.vapid_private_key.get_secret_value()
    if not private:
        log.warning("push_without_vapid_keys")
        return None
    keys = VapidKeys.from_hex(private, settings.vapid_public_key or None)
    return WebPusher(keys, settings.public_origin or DEFAULT_SUBJECT, OutboundHttp())


@cache
def telegram() -> TelegramChannel | None:
    """Second canal (PR 54) : le bot, s'il est configure."""
    current = telegram_bot()
    if current is None:
        return None
    return TelegramChannel(current, get_settings().public_origin or DEFAULT_SUBJECT)


@periodic("signals.dispatch", cron="* * * * *")
async def dispatch(ctx: JobContext, payload: dict[str, Any]) -> None:
    outcomes = await dispatch_due(ctx.database, pusher(), datetime.now(UTC), telegram=telegram())
    if outcomes:
        log.info("signals_dispatch_round", **outcomes)
