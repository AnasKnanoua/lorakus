"""Acces a l'orchestrateur des specialistes et au routage depuis les routes (PR 39)."""

from typing import cast

from fastapi import Request

from lorakus.core.agents.orchestrator import Orchestrator
from lorakus.core.agents.routing import IntentRouter


def get_orchestrator(request: Request) -> Orchestrator:
    """Dependance FastAPI : l'orchestrateur (disjoncteur et cache partages par l'API)."""
    return cast(Orchestrator, request.app.state.orchestrator)


def get_intent_router(request: Request) -> IntentRouter:
    """Dependance FastAPI : le routage des questions (vecteurs des exemples gardes en memoire)."""
    return cast(IntentRouter, request.app.state.intent_router)
