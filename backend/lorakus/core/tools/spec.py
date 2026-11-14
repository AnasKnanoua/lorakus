"""Outils : ce qu'un module permet de FAIRE, declare avec son niveau de risque (ADR 0012).

- read : lit seulement ; execute directement.
- write : modifie les donnees de l'utilisateur ; exige sa confirmation.
- sensitive : argent, sante, suppression, envoi a un tiers... ; confirmation ET preuve
  d'identite recente (re-authentification de moins de 10 minutes).
Les arguments sont valides par un schema avant toute execution.

Un outil write ou sensitive fournit `summary` : le texte de la carte de confirmation, ecrit
par le CODE a partir des arguments valides (PR 38). Celui qui demande l'action (l'utilisateur
par l'API, ou un modele dans le chat) ne choisit jamais ce que la carte affiche.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.memory.service import MemoryService

Risk = Literal["read", "write", "sensitive"]
TOOL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$")
MAX_RESULT_CHARS: Final = 4000
MAX_SUMMARY_CHARS: Final = 700


@dataclass(frozen=True)
class ToolPorts:
    """Services du Core qu'un outil peut utiliser (les modules n'en construisent aucun)."""

    memory: MemoryService | None = None


@dataclass(frozen=True)
class ToolCall:
    """Contexte d'une execution : session liee a l'utilisateur (RLS), services, provenance.

    origin : d'ou vient la demande (ex. `conversation:<id>`), pour la provenance des donnees
    creees (ADR 0015) ; None pour un appel direct par l'API.
    """

    user_id: uuid.UUID
    session: AsyncSession
    ports: ToolPorts = field(default_factory=ToolPorts)
    origin: str | None = None


ToolHandler = Callable[[ToolCall, Any], Awaitable[dict[str, Any]]]
ToolSummary = Callable[[ToolCall, Any], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    """Declaration d'un outil dans le manifeste d'un module.

    activity : courte phrase affichee quand un outil read a servi (ex. « A consulté ta
    mémoire ») ; par defaut, la description.
    """

    name: str
    description: str
    risk: Risk
    input_model: type[BaseModel]
    handler: ToolHandler
    summary: ToolSummary | None = None
    activity: str | None = None

    def __post_init__(self) -> None:
        if not TOOL_NAME.fullmatch(self.name):
            raise ValueError(f"nom d'outil invalide : {self.name} (forme module.action)")
        if not self.description.strip():
            raise ValueError(f"outil {self.name} : description obligatoire")
        if self.risk != "read" and self.summary is None:
            raise ValueError(
                f"outil {self.name} : une action {self.risk} decrit sa carte (summary)"
            )


class ToolError(Exception):
    """Appel refuse : outil inconnu ou indisponible, arguments invalides, confirmation perimee.

    Le message est montre a l'utilisateur (et au modele dans le chat) : en francais, sans
    detail technique.
    """
