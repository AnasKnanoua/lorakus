"""Manifeste du module Projets (MODULE_SYSTEM.md §2, PR 51)."""

from lorakus.core.modules.manifest import DataDeclaration, FrontendEntry, ModuleManifest
from lorakus.core.planning.service import TASK_COMPLETED

# Importer le handler l'abonne (@on) dans l'API et dans le worker.
from lorakus_modules.projects.capture import capture_idea
from lorakus_modules.projects.events import task_completed
from lorakus_modules.projects.export import export_projects
from lorakus_modules.projects.router import router
from lorakus_modules.projects.tools import TOOLS

__all__ = ["manifest", "task_completed"]


async def check_health() -> bool:
    """Le module n'a pas de dependance propre : des regles et PostgreSQL."""
    return True


manifest = ModuleManifest(
    id="projects",
    name="Projets",
    version="0.1.0",
    requires_core=">=0.3,<1.0",
    description="Boîte d'idées, projets et leurs tâches : chaque tâche entre dans le planning.",
    permissions=["projects:read", "projects:write"],
    # Consommateur de l'evenement du planning (ADR 0018) : une tache terminee depuis le chat.
    events_consumed=[TASK_COMPLETED],
    api_router=router,
    models="lorakus_modules.projects.models",
    migrations="projects",
    data=DataDeclaration(
        table_prefix="proj_",
        tables=["proj_ideas", "proj_projects", "proj_tasks"],
        classes={"proj_ideas": "personal", "proj_projects": "personal", "proj_tasks": "personal"},
    ),
    frontend=FrontendEntry(route="/projets", label="Projets", icon="folder-kanban"),
    # Outils du chat (cartes de confirmation), proposes au modele par CHAT_TOOLS (ADR 0040).
    tools=TOOLS,
    # « Mes donnees » : idees, projets et taches, meme module desactive.
    data_exporter=export_projects,
    # Capture rapide (P5, scenario 5) : un texte envoye au bot Telegram devient une idee.
    capture=capture_idea,
    health=check_health,
)
