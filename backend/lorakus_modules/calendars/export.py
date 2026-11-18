"""Export des donnees du module calendars (« Mes donnees », PR 41).

Les abonnements, SANS leur adresse : elle est un secret (elle donne acces au calendrier), et
« jamais de secret » dans un export (MODULE_SYSTEM.md §6.1). Les creneaux synchronises sont
exportes par le Core avec le reste de l'agenda.
"""

from typing import Any

from sqlalchemy import select

from lorakus.core.data.export import DataExportContext
from lorakus_modules.calendars.models import Subscription


async def export_calendars(context: DataExportContext) -> dict[str, Any]:
    async with context.open_transaction() as session:
        rows = list(
            await session.scalars(
                select(Subscription).order_by(Subscription.created_at, Subscription.id)
            )
        )
    return {
        "subscriptions": [
            {
                "id": r.id,
                "name": r.name,
                "address": r.url_hint,
                "status": r.status,
                "error_code": r.error_code,
                "entries_count": r.entries_count,
                "last_success_at": r.last_success_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }
