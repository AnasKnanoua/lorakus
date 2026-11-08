"""Routes de sante : vivacite (liveness) et disponibilite (readiness)."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from lorakus.db.database import Database, get_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sante"])

READINESS_TIMEOUT_SECONDS = 2


class HealthResponse(BaseModel):
    """Reponse de la route de vivacite."""

    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    """Reponse de la route de disponibilite."""

    status: Literal["ok", "unavailable"]


@router.get("/health")
async def health() -> HealthResponse:
    """Indique que le processus est en vie.

    Volontairement minimale : ni version, ni environnement. Exposer la version
    aiderait un attaquant a cibler une faille connue.
    """
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> ReadinessResponse:
    """Indique si l'API peut servir des requetes (base de donnees joignable).

    En cas d'echec, aucun detail technique n'est renvoye au client : il est
    seulement journalise cote serveur.
    """
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await database.ping()
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.warning("Base de donnees indisponible", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable")
    return ReadinessResponse(status="ok")
