"""Manifeste du module Template (MODULE_SYSTEM.md §2)."""

from lorakus.core.modules.manifest import DataDeclaration, FrontendEntry, ModuleManifest, Signal
from lorakus_modules._template.config import TemplateConfig
from lorakus_modules._template.router import router


async def check_health() -> bool:
    """Verification de sante : renvoyer False si le module ne peut pas travailler."""
    return True


manifest = ModuleManifest(
    id="template",
    name="Template",
    version="0.1.0",
    requires_core=">=0.1,<1.0",
    description="Module d'exemple : point de depart des nouveaux modules.",
    permissions=["template:read", "template:write"],
    config_schema=TemplateConfig,
    events_produced=["template.item_added"],
    signals_produced=[
        Signal(name="template.reminder", kind="scheduled", description="Exemple de signal"),
    ],
    api_router=router,
    models="lorakus_modules._template.models",
    migrations="template",
    data=DataDeclaration(
        table_prefix="tpl_", tables=["tpl_items"], classes={"tpl_items": "personal"}
    ),
    frontend=FrontendEntry(route="/template", label="Template", icon="box"),
    health=check_health,
)
