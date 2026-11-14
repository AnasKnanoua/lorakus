"""Acces au ToolRuntime depuis les routes (Core et modules).

Le module assistant le recoit par cette dependance pour proposer des outils au modele : il ne
construit rien lui-meme et ne contourne jamais la confirmation (PR 38).
"""

from typing import cast

from fastapi import Request

from lorakus.core.tools.runtime import ToolRuntime


def get_tools(request: Request) -> ToolRuntime:
    """Dependance FastAPI : le point de passage unique des actions."""
    return cast(ToolRuntime, request.app.state.tools)
