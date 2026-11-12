"""Acces au moteur IA depuis les routes (Core et modules).

Les modules recoivent le ModelRouter par cette dependance : ils ne connaissent ni les
fournisseurs ni leurs SDK (MODULE_SYSTEM.md §1, regles 1 et 4).
"""

from typing import cast

from fastapi import Request

from lorakus.ai.router import ModelRouter


def get_ai(request: Request) -> ModelRouter:
    """Dependance FastAPI : le routeur IA de l'application."""
    return cast(ModelRouter, request.app.state.ai)
