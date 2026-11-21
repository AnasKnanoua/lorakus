"""Notifications : /api/v1/notifications/... (P5, ADR 0042).

- Cartes (niveau 1) : `GET /cards` (3 au plus), et ce que l'utilisateur en fait :
  `POST /cards/{id}/seen` (affichee), `/close` (« OK »), `/later` (« Plus tard », 3 h).
  Toute reaction met fin a l'escalade de cette cause. `GET /cards/{id}/why` : la regle, les
  faits et chaque decision (scenario 7), aussi pour une notification deja recue.
- Appareils (niveau 2, Web Push) : `GET /push` (cle publique VAPID et appareils, jamais leur
  adresse d'abonnement), `POST /push/devices`, `DELETE /push/devices/{id}`, `POST /push/test`.

L'API ne recoit que la cle VAPID PUBLIQUE : c'est le worker qui envoie (decision D5).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.signals.service import (
    MAX_DEVICES,
    DeviceView,
    InvalidSubscriptionError,
    TooManyDevicesError,
    act_on_card,
    add_device,
    explain,
    list_cards,
    list_devices,
    remove_device,
    request_test,
)
from lorakus.core.signals.webpush import public_key_for_browser
from lorakus.db.database import Database
from lorakus.settings import get_settings

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_now() -> datetime:
    """L'instant present ; remplace dans les tests pour fixer « maintenant »."""
    return datetime.now(UTC)


User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[Database, Depends(get_database)]
Now = Annotated[datetime, Depends(get_now)]


class ReminderOut(BaseModel):
    id: uuid.UUID
    module: str
    title: str
    body: str
    url: str
    created_at: datetime


class ReminderFactOut(BaseModel):
    label: str
    value: str
    source: str
    measured: bool


class ReminderDecisionOut(BaseModel):
    level: int
    channel: Literal["app", "push"]
    reason: str
    at: datetime
    delivered: int  # appareils qui ont accepte la notification
    failed: int


class ReminderWhyOut(BaseModel):
    module: str
    rule: str
    facts: list[ReminderFactOut]
    status: str
    outcome: str | None
    created_at: datetime
    interventions: list[ReminderDecisionOut]


class PushDeviceOut(BaseModel):
    id: uuid.UUID
    label: str
    service: str  # domaine du service de notification (fcm.googleapis.com...)
    created_at: datetime
    last_success_at: datetime | None


class PushInfoOut(BaseModel):
    available: bool  # cles VAPID configurees sur le serveur
    public_key: str | None  # format attendu par pushManager.subscribe
    devices: list[PushDeviceOut]
    max_devices: int


class PushDeviceKeys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=100)
    auth: str = Field(min_length=16, max_length=30)


class PushDeviceIn(BaseModel):
    """L'abonnement tel que le rend le navigateur (PushSubscription.toJSON) et un nom."""

    endpoint: str = Field(min_length=10, max_length=1024)
    keys: PushDeviceKeys
    label: str = Field(min_length=1, max_length=60)


def _device(view: DeviceView) -> PushDeviceOut:
    return PushDeviceOut(
        id=view.id,
        label=view.label,
        service=view.service,
        created_at=view.created_at,
        last_success_at=view.last_success_at,
    )


def _public_key() -> str | None:
    key = get_settings().vapid_public_key
    return public_key_for_browser(key) if key else None


@router.get("/cards")
async def cards(user: User, database: Db, now: Now) -> list[ReminderOut]:
    async with database.transaction(user.id) as session:
        return [
            ReminderOut(
                id=c.id,
                module=c.module,
                title=c.title,
                body=c.body,
                url=c.url,
                created_at=c.created_at,
            )
            for c in await list_cards(session, now)
        ]


@router.post("/cards/{card_id}/{action}", status_code=status.HTTP_204_NO_CONTENT)
async def act(
    card_id: uuid.UUID,
    action: Literal["seen", "close", "later"],
    user: User,
    database: Db,
    now: Now,
) -> Response:
    async with database.transaction(user.id) as session:
        found = await act_on_card(session, card_id, action, now)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carte inconnue.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cards/{card_id}/why")
async def why(card_id: uuid.UUID, user: User, database: Db) -> ReminderWhyOut:
    async with database.transaction(user.id) as session:
        found = await explain(session, card_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carte inconnue.")
    facts: list[dict[str, Any]] = found.facts
    return ReminderWhyOut(
        module=found.module,
        rule=found.rule,
        facts=[ReminderFactOut.model_validate(f) for f in facts],
        status=found.status,
        outcome=found.outcome,
        created_at=found.created_at,
        interventions=[
            ReminderDecisionOut(
                level=i.level,
                channel="app" if i.channel == "app" else "push",
                reason=i.reason,
                at=i.created_at,
                delivered=i.delivered,
                failed=i.failed,
            )
            for i in found.interventions
        ],
    )


@router.get("/push")
async def push(user: User, database: Db) -> PushInfoOut:
    key = _public_key()
    async with database.transaction(user.id) as session:
        devices = await list_devices(session)
    return PushInfoOut(
        available=key is not None,
        public_key=key,
        devices=[_device(d) for d in devices],
        max_devices=MAX_DEVICES,
    )


@router.post("/push/devices", status_code=status.HTTP_201_CREATED)
async def subscribe(body: PushDeviceIn, user: User, database: Db) -> PushDeviceOut:
    if _public_key() is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Notifications indisponibles sur ce serveur.")
    try:
        async with database.transaction(user.id) as session:
            device = await add_device(
                session, user.id, body.endpoint, body.keys.p256dh, body.keys.auth, body.label
            )
    except InvalidSubscriptionError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except TooManyDevicesError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{MAX_DEVICES} appareils au plus : retire-en un."
        ) from None
    return _device(device)


@router.delete("/push/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(device_id: uuid.UUID, user: User, database: Db) -> Response:
    async with database.transaction(user.id) as session:
        removed = await remove_device(session, device_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appareil inconnu.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/push/test", status_code=status.HTTP_202_ACCEPTED)
async def test(user: User, database: Db, now: Now) -> Response:
    """Notification de test vers tous les appareils, envoyee par le worker (une minute au
    plus) : le meme chemin que les vraies notifications."""
    async with database.transaction(user.id) as session:
        sent = await request_test(session, user.id, now)
    if not sent:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucun appareil abonné.")
    return Response(status_code=status.HTTP_202_ACCEPTED)
