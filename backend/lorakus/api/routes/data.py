"""Mes donnees : /api/v1/data/... (PR 41, SECURITY.md §10).

L'export contient tout ce que Lorakus garde sur l'utilisateur : il exige une preuve
d'identite de moins de 10 minutes (comme « Tout oublier »), ne passe par aucun cache et
arrive en piece jointe.
"""

import json
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response

from lorakus.api.auth import client_ip, recent_user
from lorakus.core.data.export import DataExportService
from lorakus.core.identity.service import CurrentUser

router = APIRouter(prefix="/v1/data", tags=["mes donnees"])


def get_data_export(request: Request) -> DataExportService:
    return cast(DataExportService, request.app.state.data_export)


RecentUser = Annotated[CurrentUser, Depends(recent_user)]
Export = Annotated[DataExportService, Depends(get_data_export)]


@router.get(
    "/export",
    response_class=Response,
    responses={
        200: {
            "description": "Toutes les donnees de l'utilisateur, en piece jointe JSON.",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        403: {"description": "Preuve d'identite trop ancienne (reauth_required)."},
    },
)
async def export_my_data(request: Request, user: RecentUser, service: Export) -> Response:
    """Telecharge l'export complet (jamais d'empreinte, de secret ni de vecteur)."""
    data = await service.export(user, client_ip(request))
    filename = f"lorakus-export-{datetime.now(UTC):%Y-%m-%d}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
