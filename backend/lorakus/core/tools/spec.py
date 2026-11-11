"""Outils : ce qu'un module permet de FAIRE, declare avec son niveau de risque (ADR 0012).

- read : lit seulement ; execute directement.
- write : modifie les donnees de l'utilisateur ; exige sa confirmation.
- sensitive : argent, sante, suppression, envoi a un tiers... ; confirmation ET preuve
  d'identite recente (re-authentification de moins de 10 minutes).
Les arguments sont valides par un schema avant toute execution.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

Risk = Literal["read", "write", "sensitive"]
TOOL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$")
MAX_RESULT_CHARS: Final = 4000


@dataclass(frozen=True)
class ToolCall:
    """Contexte d'une execution : session liee a l'utilisateur (RLS)."""

    user_id: Any
    session: AsyncSession


ToolHandler = Callable[[ToolCall, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """Declaration d'un outil dans le manifeste d'un module."""

    name: str
    description: str
    risk: Risk
    input_model: type[BaseModel]
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not TOOL_NAME.fullmatch(self.name):
            raise ValueError(f"nom d'outil invalide : {self.name} (forme module.action)")
        if not self.description.strip():
            raise ValueError(f"outil {self.name} : description obligatoire")
