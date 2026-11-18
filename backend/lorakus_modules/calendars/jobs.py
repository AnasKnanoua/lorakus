"""Job unique de synchronisation des calendriers (MODULE_SYSTEM.md §11, ADR 0041).

Chaque minute, il traite ce qui est du pour TOUS les utilisateurs (abonnement nouveau,
« Synchroniser maintenant », 30 minutes apres la derniere reussite, ou apres l'attente qui
suit un echec). Aucun minuteur par utilisateur.
"""

from datetime import UTC, datetime
from functools import cache
from typing import Any

import structlog

from lorakus.core.identity.crypto import FieldCipher
from lorakus.core.jobs.port import JobContext, periodic
from lorakus.core.outbound import OutboundHttp
from lorakus.settings import get_settings
from lorakus_modules.calendars.service import sync_due

log = structlog.get_logger("lorakus.calendars")


@cache
def _http() -> OutboundHttp:
    """Client sortant du Core, avec la politique de production (adresses publiques seules)."""
    return OutboundHttp()


@periodic("calendars.sync", cron="* * * * *")
async def sync_calendars(ctx: JobContext, payload: dict[str, Any]) -> None:
    cipher = FieldCipher.for_connectors(get_settings())
    if cipher is None:  # developpement sans cle : rien a dechiffrer
        log.warning("calendar_sync_without_key")
        return
    outcomes = await sync_due(ctx.database, cipher, _http(), datetime.now(UTC))
    if outcomes:
        log.info("calendar_sync_round", **outcomes)
