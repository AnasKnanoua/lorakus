"""Acces a la memoire et aux taches de fond depuis les routes (Core et modules)."""

from typing import cast

from fastapi import Request

from lorakus.core.background import DebouncedTasks
from lorakus.core.memory.service import MemoryService


def get_memory(request: Request) -> MemoryService:
    """Dependance FastAPI : le service de memoire de l'application."""
    return cast(MemoryService, request.app.state.memory)


def get_background(request: Request) -> DebouncedTasks:
    """Dependance FastAPI : les taches de fond regroupees de l'application."""
    return cast(DebouncedTasks, request.app.state.background)
