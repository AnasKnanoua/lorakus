"""Reglages du compte : /api/v1/account/... (PR 44, ADR 0018).

Le fuseau horaire est le seul reglage pour l'instant. L'interface envoie le fuseau du
navigateur et propose de le changer s'il differe : jamais de changement silencieux, car les
travaux de nuit (sans navigateur) lisent ce reglage.
"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from lorakus.api.auth import client_ip, current_user
from lorakus.core.account.clock import DEFAULT_TIMEZONE, MAX_TZ_CHARS, InvalidTimezoneError
from lorakus.core.account.service import set_timezone, timezone_name
from lorakus.core.identity.service import CurrentUser
from lorakus.db.database import Database

router = APIRouter(prefix="/v1/account", tags=["compte"])


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[Database, Depends(get_database)]


class AccountSettingsOut(BaseModel):
    timezone: str
    default_timezone: str


class TimezoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(min_length=1, max_length=MAX_TZ_CHARS)


@router.get("/settings")
async def read_settings(user: User, database: Db) -> AccountSettingsOut:
    async with database.transaction(user.id) as session:
        name = await timezone_name(session)
    return AccountSettingsOut(timezone=name, default_timezone=DEFAULT_TIMEZONE)


@router.put("/timezone")
async def update_timezone(
    body: TimezoneIn, request: Request, user: User, database: Db
) -> AccountSettingsOut:
    try:
        async with database.transaction(user.id) as session:
            name = await set_timezone(session, user.id, body.timezone, client_ip(request))
    except InvalidTimezoneError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Fuseau horaire inconnu."
        ) from None
    return AccountSettingsOut(timezone=name, default_timezone=DEFAULT_TIMEZONE)
