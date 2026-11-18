"""Routes du module calendars, montees sous /api/v1/calendars (PR 45).

L'adresse d'un abonnement est recue une fois, a la creation, puis JAMAIS renvoyee : les
reponses ne donnent que son domaine (`hint`). Aucune route ne telecharge quoi que ce soit :
la synchronisation se fait dans le worker.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from lorakus.api.auth import client_ip, current_user
from lorakus.api.connectors import get_connector_cipher
from lorakus.core.identity.crypto import FieldCipher
from lorakus.core.identity.service import CurrentUser, audit
from lorakus.db.database import Database
from lorakus_modules.calendars.service import (
    MAX_NAME_CHARS,
    SubscriptionError,
    SubscriptionNotFoundError,
    SubscriptionView,
    add_subscription,
    delete_subscription,
    list_subscriptions,
    request_sync,
)

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]
Cipher = Annotated[FieldCipher, Depends(get_connector_cipher)]
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Calendrier introuvable.")


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    url: str = Field(min_length=1, max_length=2048)


class SubscriptionOut(BaseModel):
    """Un abonnement, sans son adresse (secrete) : seulement son domaine."""

    id: uuid.UUID
    name: str
    hint: str
    status: Literal["pending", "ok", "error"]
    error: str | None
    entries_count: int
    skipped_count: int
    truncated: bool
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_sync_at: datetime
    created_at: datetime


def _out(view: SubscriptionView) -> SubscriptionOut:
    return SubscriptionOut(
        id=view.id,
        name=view.name,
        hint=view.hint,
        status=cast(Literal["pending", "ok", "error"], view.status),
        error=view.error,
        entries_count=view.entries_count,
        skipped_count=view.skipped_count,
        truncated=view.truncated,
        last_attempt_at=view.last_attempt_at,
        last_success_at=view.last_success_at,
        next_sync_at=view.next_sync_at,
        created_at=view.created_at,
    )


@router.get("/subscriptions")
async def get_subscriptions(request: Request, user: User) -> list[SubscriptionOut]:
    async with _database(request).transaction(user.id) as session:
        return [_out(v) for v in await list_subscriptions(session)]


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionIn, request: Request, user: User, cipher: Cipher
) -> SubscriptionOut:
    try:
        async with _database(request).transaction(user.id) as session:
            view = await add_subscription(session, cipher, user.id, body.name, body.url)
            await audit(
                session,
                user.id,
                "calendars.subscription_add",
                "success",
                client_ip(request),
                {"subscription_id": str(view.id)},
            )
    except SubscriptionError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return _out(view)


@router.post("/subscriptions/{subscription_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(subscription_id: uuid.UUID, request: Request, user: User) -> SubscriptionOut:
    try:
        async with _database(request).transaction(user.id) as session:
            return _out(await request_sync(session, subscription_id))
    except SubscriptionNotFoundError:
        raise NOT_FOUND from None


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(subscription_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            removed = await delete_subscription(session, subscription_id)
            await audit(
                session,
                user.id,
                "calendars.subscription_delete",
                "success",
                client_ip(request),
                {"subscription_id": str(subscription_id), "entries": removed},
            )
    except SubscriptionNotFoundError:
        raise NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
