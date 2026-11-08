"""Route de sante : permet de verifier que l'API repond."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["sante"])


class HealthResponse(BaseModel):
    """Reponse de la route de sante."""

    status: Literal["ok"]


@router.get("/health")
async def health() -> HealthResponse:
    """Indique que l'API est en vie.

    Volontairement minimale : ni version, ni environnement. Exposer la version
    aiderait un attaquant a cibler une faille connue. Ces details iront dans
    /admin, reserve aux administrateurs.
    """
    return HealthResponse(status="ok")
