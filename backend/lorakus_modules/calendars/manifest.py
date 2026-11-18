"""Manifeste du module Calendars (MODULE_SYSTEM.md §2, ADR 0041)."""

from lorakus.core.modules.manifest import DataDeclaration, FrontendEntry, ModuleManifest
from lorakus_modules.calendars.export import export_calendars

# Importer le job l'enregistre (@periodic) dans l'API et dans le worker.
from lorakus_modules.calendars.jobs import sync_calendars
from lorakus_modules.calendars.router import router

__all__ = ["manifest", "sync_calendars"]


async def check_health() -> bool:
    """Le module n'a pas de dependance propre : l'etat des synchronisations est par abonnement."""
    return True


manifest = ModuleManifest(
    id="calendars",
    name="Calendriers",
    version="0.1.0",
    requires_core=">=0.3,<1.0",
    description="Abonnements ICS en lecture : les evenements arrivent dans l'agenda.",
    permissions=["calendars:read", "calendars:write"],
    api_router=router,
    models="lorakus_modules.calendars.models",
    migrations="calendars",
    data=DataDeclaration(
        table_prefix="cal_",
        tables=["cal_subscriptions"],
        classes={"cal_subscriptions": "personal"},
    ),
    frontend=FrontendEntry(route="/calendriers", label="Calendriers", icon="calendar-sync"),
    # « Mes donnees » : les abonnements sans leur adresse secrete.
    data_exporter=export_calendars,
    health=check_health,
)
