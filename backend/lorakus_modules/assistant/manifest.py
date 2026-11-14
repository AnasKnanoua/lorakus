"""Manifeste du module Assistant (MODULE_SYSTEM.md §2) : le Majordome (ADR 0025)."""

from lorakus.core.modules.manifest import DataDeclaration, FrontendEntry, ModuleManifest
from lorakus_modules.assistant.config import AssistantConfig
from lorakus_modules.assistant.router import router
from lorakus_modules.assistant.tools import TOOLS


async def check_health() -> bool:
    """Le module n'a pas de dependance propre : l'etat de l'IA est suivi par ses metriques."""
    return True


manifest = ModuleManifest(
    id="assistant",
    name="Assistant",
    version="0.2.0",
    requires_core=">=0.2,<1.0",
    description="Conversation avec l'assistant, en streaming, avec reponse de secours.",
    permissions=["assistant:read", "assistant:write"],
    config_schema=AssistantConfig,
    api_router=router,
    models="lorakus_modules.assistant.models",
    migrations="assistant",
    data=DataDeclaration(
        table_prefix="asst_",
        tables=["asst_conversations", "asst_messages"],
        classes={"asst_conversations": "personal", "asst_messages": "personal"},
    ),
    frontend=FrontendEntry(route="/chat", label="Discuter", icon="message-circle"),
    # Outils du chat (PR 38) : la memoire, avec confirmation pour toute modification.
    tools=TOOLS,
    health=check_health,
)
