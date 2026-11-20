"""Manifeste du module Academic (MODULE_SYSTEM.md §2, PR 46)."""

from lorakus.core.modules.manifest import DataDeclaration, FrontendEntry, ModuleManifest
from lorakus.core.planning.service import TASK_COMPLETED

# Importer le handler l'abonne (@on) dans l'API et dans le worker.
from lorakus_modules.academic.events import task_completed
from lorakus_modules.academic.export import export_academic
from lorakus_modules.academic.router import router
from lorakus_modules.academic.tools import TOOLS

__all__ = ["manifest", "task_completed"]


async def check_health() -> bool:
    """Le module n'a pas de dependance propre : des regles et PostgreSQL."""
    return True


manifest = ModuleManifest(
    id="academic",
    name="Cours",
    version="0.1.0",
    requires_core=">=0.3,<1.0",
    description="Cours et evaluations (devoirs, examens) : chacune cree sa tache.",
    permissions=["academic:read", "academic:write"],
    # Premier consommateur de l'evenement du planning (ADR 0018).
    events_consumed=[TASK_COMPLETED],
    api_router=router,
    models="lorakus_modules.academic.models",
    migrations="academic",
    data=DataDeclaration(
        table_prefix="acad_",
        tables=["acad_courses", "acad_assessments"],
        classes={"acad_courses": "personal", "acad_assessments": "personal"},
    ),
    frontend=FrontendEntry(route="/academic", label="Cours", icon="graduation-cap"),
    # Outil du chat (carte de confirmation), propose au modele par CHAT_TOOLS (ADR 0040).
    tools=TOOLS,
    # « Mes donnees » : cours et evaluations, meme module desactive.
    data_exporter=export_academic,
    health=check_health,
)
