"""Preparations : /api/v1/preparations (P5, ADR 0028).

- `GET /api/v1/preparations` : ce qui a ete prepare pour toi et n'a pas encore ete lu (le
  briefing du lendemain), la plus recente d'abord, trois au plus.
- `POST /api/v1/preparations/{id}/consulted` : lue ; figee, elle n'est plus montree.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.preparations.service import consult, list_ready
from lorakus.db.database import Database

router = APIRouter(prefix="/v1/preparations", tags=["preparations"])


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_now() -> datetime:
    """L'instant present ; remplace dans les tests pour fixer « maintenant »."""
    return datetime.now(UTC)


User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[Database, Depends(get_database)]
Now = Annotated[datetime, Depends(get_now)]


class PreparationSectionOut(BaseModel):
    heading: str
    lines: list[str]


class PreparationOut(BaseModel):
    id: uuid.UUID
    module: str
    kind: str
    day: date
    title: str
    sections: list[PreparationSectionOut]
    prepared_at: datetime


@router.get("")
async def preparations(user: User, database: Db, now: Now) -> list[PreparationOut]:
    async with database.transaction(user.id) as session:
        found = await list_ready(session, now)
    return [
        PreparationOut(
            id=p.id,
            module=p.module,
            kind=p.kind,
            day=p.day,
            title=p.title,
            sections=[
                PreparationSectionOut(heading=s.heading, lines=list(s.lines)) for s in p.sections
            ],
            prepared_at=p.prepared_at,
        )
        for p in found
    ]


@router.post("/{preparation_id}/consulted", status_code=status.HTTP_204_NO_CONTENT)
async def consulted(preparation_id: uuid.UUID, user: User, database: Db, now: Now) -> Response:
    async with database.transaction(user.id) as session:
        found = await consult(session, preparation_id, now)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Préparation inconnue.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
