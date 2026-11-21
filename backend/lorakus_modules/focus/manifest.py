"""Manifeste du module Focus : le Sergent (MODULE_SYSTEM.md §2, PR 50)."""

from lorakus.core.modules.manifest import ModuleManifest
from lorakus_modules.focus.specialist import PROFILE
from lorakus_modules.focus.tools import TOOLS

__all__ = ["manifest"]


async def check_health() -> bool:
    """Des regles sur les donnees du planning : aucune dependance propre."""
    return True


manifest = ModuleManifest(
    id="focus",
    name="Sergent",
    version="0.1.0",
    requires_core=">=0.3,<1.0",
    description=(
        "Le Sergent : ta journée et tes échéances, calculées à partir de tes tâches, de ton "
        "agenda et de ce que tu as dit de ta journée ; découpe une tâche longue en étapes."
    ),
    permissions=["focus:read", "focus:write"],
    # Aucune table : il lit le planning du Core (ADR 0018), sous la RLS de l'utilisateur.
    specialist=PROFILE,
    tools=TOOLS,
    health=check_health,
)
