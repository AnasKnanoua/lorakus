"""Le bot du worker, construit une fois a partir des reglages (sans registre des modules : le
dispatch des rappels l'utilise et ne doit dependre d'aucun modele de langage)."""

from functools import cache

import structlog

from lorakus.core.outbound import OutboundHttp
from lorakus.core.telegram.bot import TelegramBot
from lorakus.settings import get_settings

log = structlog.get_logger("lorakus.telegram")


@cache
def bot() -> TelegramBot | None:
    """Le bot, ou None sans jeton. Un jeton mal forme empeche le worker de demarrer."""
    token = get_settings().telegram_bot_token.get_secret_value()
    if not token:
        log.warning("telegram_without_token")
        return None
    return TelegramBot(token, OutboundHttp())
