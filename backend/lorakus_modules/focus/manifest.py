"""Manifeste du module Focus : le Sergent (MODULE_SYSTEM.md §2, PR 50)."""

from lorakus.core.modules.manifest import ModuleManifest, Signal

# Importer les jobs les enregistre (@periodic) dans l'API et dans le worker.
from lorakus_modules.focus.briefing import briefing
from lorakus_modules.focus.specialist import PROFILE
from lorakus_modules.focus.tools import TOOLS
from lorakus_modules.focus.watch import SIGNAL, deadline_watch

__all__ = ["briefing", "deadline_watch", "manifest"]


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
    # Prendre les devants (P5, ADR 0042) : un seul rappel avant une echeance, decide par la
    # politique d'intervention du Core (jamais une notification directe).
    signals_produced=[
        Signal(
            name=SIGNAL,
            kind="scheduled",
            description="Tâche à rendre dans 3 jours ou moins, sans étape terminée.",
        )
    ],
    tools=TOOLS,
    health=check_health,
)
