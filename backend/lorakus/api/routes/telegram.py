"""Bot Telegram : /api/v1/telegram (P5, PR 54).

- `GET` : le bot est-il configure sur le serveur, ce compte est-il lie, et les rappels y
  arrivent-ils aussi (sans detail).
- `POST /code` : un code de liaison (10 minutes, usage unique), a envoyer au bot.
- `PUT` : recevoir aussi les rappels par Telegram, ou non.
- `DELETE` : delier.

L'API ne recoit jamais le jeton du bot (decision D5) : c'est le worker qui releve les messages
et y repond.
"""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.telegram.service import link_status, new_code, set_notify, unlink
from lorakus.db.database import Database
from lorakus.settings import get_settings

router = APIRouter(prefix="/v1/telegram", tags=["telegram"])


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_now() -> datetime:
    """L'instant present ; remplace dans les tests pour fixer « maintenant »."""
    return datetime.now(UTC)


User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[Database, Depends(get_database)]
Now = Annotated[datetime, Depends(get_now)]


class TelegramOut(BaseModel):
    available: bool  # bot configure sur le serveur
    linked: bool
    notify: bool  # recevoir aussi les rappels ici, sans detail
    linked_at: datetime | None
    last_message_at: datetime | None


class TelegramCodeOut(BaseModel):
    code: str  # « K7QM-2XPH »
    expires_at: datetime


class TelegramIn(BaseModel):
    notify: bool


async def _status(database: Database, user: CurrentUser) -> TelegramOut:
    async with database.transaction(user.id) as session:
        link = await link_status(session)
    return TelegramOut(
        available=get_settings().telegram_available,
        linked=link is not None,
        notify=link is not None and link.notify,
        linked_at=link.linked_at if link else None,
        last_message_at=link.last_message_at if link else None,
    )


@router.get("")
async def telegram(user: User, database: Db) -> TelegramOut:
    return await _status(database, user)


@router.post("/code", status_code=status.HTTP_201_CREATED)
async def code(user: User, database: Db, now: Now) -> TelegramCodeOut:
    if not get_settings().telegram_available:
        raise HTTPException(status.HTTP_409_CONFLICT, "Le bot Telegram n'est pas configuré.")
    async with database.transaction(user.id) as session:
        created = await new_code(session, user.id, now)
    return TelegramCodeOut(code=created.code, expires_at=created.expires_at)


@router.put("")
async def choose(body: TelegramIn, user: User, database: Db) -> TelegramOut:
    async with database.transaction(user.id) as session:
        found = await set_notify(session, body.notify)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun compte Telegram lié.")
    return await _status(database, user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def forget(user: User, database: Db) -> Response:
    async with database.transaction(user.id) as session:
        removed = await unlink(session)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun compte Telegram lié.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
