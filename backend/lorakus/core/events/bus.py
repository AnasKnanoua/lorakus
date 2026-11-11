"""Evenements : publication transactionnelle (outbox) et livraison au moins une fois.

    await publish(session, "academic.deadline_added", {"deadline_id": "..."}, user_id=user.id)

    @on("academic.deadline_added")
    async def plan_revision(event: Event, session: AsyncSession) -> None: ...

- publish() ecrit dans la transaction de l'appelant : l'evenement n'existe que si le
  changement qui le cause est valide (pas d'evenement fantome, pas d'evenement perdu).
- Le worker livre chaque evenement a chacun de ses handlers, dans une transaction liee a
  l'utilisateur de l'evenement (RLS). Un handler reussi n'est pas rejoue ; un handler en
  echec est retente avec une attente croissante, puis l'evenement est mis de cote (« mort »).
- Charge utile : des identifiants, jamais de donnees personnelles (elles restent en base).
"""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EVENT_TYPE: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$")
MAX_PAYLOAD_KEYS: Final = 20


@dataclass(frozen=True)
class Event:
    """Evenement livre a un handler."""

    id: int
    type: str
    user_id: uuid.UUID | None
    payload: dict[str, Any]
    attempt: int


Handler = Callable[[Event, AsyncSession], Awaitable[None]]


@dataclass
class EventBus:
    """Abonnements : type d'evenement -> handlers (nom stable -> fonction)."""

    handlers: dict[str, dict[str, Handler]] = field(default_factory=dict[str, dict[str, Handler]])

    def subscribe(self, event_type: str, handler: Handler, name: str | None = None) -> None:
        check_event_type(event_type)
        key = name or f"{handler.__module__}.{handler.__qualname__}"
        subscribers = self.handlers.setdefault(event_type, {})
        if key in subscribers:
            raise ValueError(f"handler deja abonne a {event_type} : {key}")
        subscribers[key] = handler

    def handlers_for(self, event_type: str) -> dict[str, Handler]:
        return dict(self.handlers.get(event_type, {}))


# Bus du processus : les modules s'y abonnent par @on a l'import.
bus: Final = EventBus()


def on(event_type: str, *, name: str | None = None) -> Callable[[Handler], Handler]:
    """Decorateur : abonne une fonction a un type d'evenement."""

    def decorator(handler: Handler) -> Handler:
        bus.subscribe(event_type, handler, name)
        return handler

    return decorator


def check_event_type(event_type: str) -> None:
    if not EVENT_TYPE.fullmatch(event_type):
        raise ValueError(f"type d'evenement invalide : {event_type} (forme module.nom)")


async def publish(
    session: AsyncSession,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: uuid.UUID | None,
) -> None:
    """Publie dans la transaction en cours (session liee a user_id, ou evenement systeme)."""
    check_event_type(event_type)
    payload = payload or {}
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise ValueError("charge utile trop grosse : des identifiants seulement")
    # INSERT sans RETURNING : relire la ligne exigerait de la voir, ce que la RLS refuse pour
    # un evenement systeme (sans utilisateur).
    await session.execute(
        text(
            "INSERT INTO lorakus.core_outbox (user_id, event_type, payload) "
            "VALUES (:user_id, :event_type, CAST(:payload AS jsonb))"
        ),
        {"user_id": user_id, "event_type": event_type, "payload": json.dumps(payload)},
    )
