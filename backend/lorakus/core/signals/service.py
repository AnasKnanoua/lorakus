"""Signaux (ADR 0019 et 0042) : le seul chemin par lequel un module propose d'interrompre.

    from lorakus.core.signals.service import Fact, SignalDraft, emit
    await emit(session, user_id, "focus", SignalDraft(...), now)

Un module ne notifie jamais lui-meme : il emet un signal (une cause, avec son texte et ses
faits), et la politique d'intervention (policy.py, job `signals.dispatch`) decide seule si,
quand et comment interrompre. Une cause n'existe qu'une fois (`dedup_key` unique) : emettre
de nouveau le meme signal ne change rien, et un signal retire ne revient pas.

Tout ici s'execute dans la transaction de l'appelant, sous la RLS de l'utilisateur.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from prometheus_client import Counter
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.planning.models import Task
from lorakus.core.planning.service import clean_line
from lorakus.core.signals.models import InterventionRow, PushSubscriptionRow, SignalRow
from lorakus.core.signals.policy import TEST_SIGNAL
from lorakus.core.signals.webpush import (
    InvalidSubscriptionError,
    check_auth_secret,
    check_endpoint,
    load_device_key,
    push_host,
)

SIGNAL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$")
URL: Final = re.compile(r"^/[a-z]+(/[a-z0-9_-]+)*$")
Kind = Literal["scheduled", "contextual", "proactive"]
DataClass = Literal["public", "personal", "sensitive"]
CardAction = Literal["seen", "close", "later"]

MAX_LIFETIME: Final = timedelta(days=14)
MAX_FACTS: Final = 12
MAX_CARDS: Final = 3  # cartes affichees a la fois (ADR 0028)
SNOOZE: Final = timedelta(hours=3)  # « Plus tard »
MAX_DEVICES: Final = 10
TEST_LIFETIME: Final = timedelta(minutes=10)

EMITTED = Counter(
    "lorakus_signals_emitted_total",
    "Signaux emis par les modules (new : cause nouvelle ; known : deja connue)",
    ["name", "outcome"],
)


class InvalidSignalError(ValueError):
    """Signal mal forme : une erreur de programmation du module emetteur."""


class TooManyDevicesError(Exception):
    """Trop d'appareils abonnes."""


@dataclass(frozen=True)
class Fact:
    """Un fait montre par « Pourquoi ? » : d'ou il vient, mesure ou estime."""

    label: str
    value: str
    source: str
    measured: bool = True


@dataclass(frozen=True)
class SignalDraft:
    """Ce qu'un module propose. Les textes sont ecrits par le code du module, jamais par un
    modele, et ne contiennent que ce que la notification peut montrer."""

    name: str
    kind: Kind
    strength: float
    data_class: DataClass
    dedup_key: str
    title: str
    body: str
    rule: str
    url: str
    not_before: datetime
    expires_at: datetime
    subject_ref: str | None = None
    firm_body: str | None = None
    facts: Sequence[Fact] = field(default_factory=tuple[Fact, ...])


def _checked(module: str, draft: SignalDraft) -> dict[str, Any]:
    if not SIGNAL_NAME.fullmatch(draft.name) or draft.name.split(".", 1)[0] != module:
        raise InvalidSignalError(f"signal '{draft.name}' : doit commencer par '{module}.'")
    if not 0 <= draft.strength <= 1:
        raise InvalidSignalError("strength : entre 0 et 1")
    if not URL.fullmatch(draft.url):
        raise InvalidSignalError(f"url '{draft.url}' : chemin de l'application attendu")
    if not draft.not_before < draft.expires_at <= draft.not_before + MAX_LIFETIME:
        raise InvalidSignalError("expires_at : apres not_before, 14 jours au plus")
    if len(draft.facts) > MAX_FACTS:
        raise InvalidSignalError(f"{MAX_FACTS} faits au plus")
    try:
        return {
            "module": module,
            "name": draft.name,
            "kind": draft.kind,
            "strength": draft.strength,
            "data_class": draft.data_class,
            "subject_ref": draft.subject_ref,
            "dedup_key": clean_line(draft.dedup_key, 200, "cle"),
            "title": clean_line(draft.title, 120),
            "body": clean_line(draft.body, 400, "texte"),
            "firm_body": None if draft.firm_body is None else clean_line(draft.firm_body, 400),
            "rule": clean_line(draft.rule, 300, "regle"),
            "facts": [
                {
                    "label": clean_line(f.label, 60),
                    "value": clean_line(f.value, 200),
                    "source": clean_line(f.source, 60),
                    "measured": f.measured,
                }
                for f in draft.facts
            ],
            "url": draft.url,
            "not_before": draft.not_before,
            "expires_at": draft.expires_at,
        }
    except ValueError as error:
        raise InvalidSignalError(str(error)) from None


async def emit(session: AsyncSession, user_id: uuid.UUID, module: str, draft: SignalDraft) -> bool:
    """Enregistre la cause si elle est nouvelle ; True si elle l'est. Aucun effet sinon,
    meme si le signal avait ete retire, avait expire ou avait deja donne une notification."""
    values = _checked(module, draft)
    inserted = await session.scalar(
        insert(SignalRow)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            status="active",
            next_check_at=draft.not_before,
            **values,
        )
        .on_conflict_do_nothing(constraint="uq_core_signals_user_id_dedup_key")
        .returning(SignalRow.id)
    )
    EMITTED.labels(name=draft.name, outcome="new" if inserted else "known").inc()
    return inserted is not None


async def withdraw(session: AsyncSession, module: str, dedup_key: str, reason: str) -> bool:
    """Retire une cause qui n'en est plus une (tache commencee, terminee...) : plus de
    decision, et sa carte disparait. True si un signal encore vivant a ete retire."""
    result = await session.execute(
        update(SignalRow)
        .where(
            SignalRow.module == module,
            SignalRow.dedup_key == dedup_key,
            SignalRow.status.in_(("active", "done")),
        )
        .values(status="withdrawn", outcome=reason[:40], next_check_at=None, locked_until=None)
        .returning(SignalRow.id)
    )
    return result.first() is not None


async def live_keys(session: AsyncSession, module: str, name: str) -> set[str]:
    """Cles des signaux encore vivants (en decision, ou carte encore valable) d'un module."""
    rows = await session.scalars(
        select(SignalRow.dedup_key).where(
            SignalRow.module == module,
            SignalRow.name == name,
            SignalRow.status.in_(("active", "done")),
        )
    )
    return set(rows)


# ---------------------------------------------------------------------- cartes
@dataclass(frozen=True)
class CardView:
    id: uuid.UUID
    module: str
    title: str
    body: str
    url: str
    created_at: datetime


def task_ref(subject_ref: str | None) -> uuid.UUID | None:
    """Identifiant de la tache visee par `task:<uuid>`, ou None."""
    if subject_ref is None or not subject_ref.startswith("task:"):
        return None
    try:
        return uuid.UUID(subject_ref[5:])
    except ValueError:
        return None


async def open_tasks_among(session: AsyncSession, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await session.scalars(select(Task.id).where(Task.id.in_(ids), Task.status == "open"))
    return set(rows)


async def list_cards(session: AsyncSession, now: datetime) -> list[CardView]:
    """Cartes du niveau 1 a montrer maintenant : les plus fortes d'abord, 3 au plus.

    Une carte dont la tache a ete terminee ou supprimee entre-temps n'est plus montree,
    sans attendre que le job la retire (lecture seule ici)."""
    rows = list(
        await session.scalars(
            select(SignalRow)
            .join(
                InterventionRow,
                (InterventionRow.signal_id == SignalRow.id) & (InterventionRow.level == 1),
            )
            .where(
                SignalRow.status.in_(("active", "done")),
                SignalRow.closed_at.is_(None),
                SignalRow.expires_at > now,
                (SignalRow.snoozed_until.is_(None)) | (SignalRow.snoozed_until <= now),
            )
            .order_by(SignalRow.strength.desc(), SignalRow.created_at, SignalRow.id)
            .limit(20)
        )
    )
    open_ids = await open_tasks_among(
        session, {ref for row in rows if (ref := task_ref(row.subject_ref)) is not None}
    )
    cards = [
        CardView(row.id, row.module, row.title, row.body, row.url, row.created_at)
        for row in rows
        if (ref := task_ref(row.subject_ref)) is None or ref in open_ids
    ]
    return cards[:MAX_CARDS]


async def act_on_card(
    session: AsyncSession, signal_id: uuid.UUID, action: CardAction, now: datetime
) -> bool:
    """Vue (affichee), fermee (« OK ») ou repoussee (« Plus tard », 3 h) ; False si inconnue.
    Toute reaction compte comme vue : la politique n'escalade plus jamais cette cause."""
    values: dict[str, Any] = {"seen_at": func.coalesce(SignalRow.seen_at, now)}
    if action == "close":
        values["closed_at"] = func.coalesce(SignalRow.closed_at, now)
    elif action == "later":
        values["snoozed_until"] = now + SNOOZE
    result = await session.execute(
        update(SignalRow)
        .where(SignalRow.id == signal_id, SignalRow.name != TEST_SIGNAL)
        .values(**values)
        .returning(SignalRow.id)
    )
    return result.first() is not None


@dataclass(frozen=True)
class InterventionView:
    level: int
    channel: str
    reason: str
    created_at: datetime
    delivered: int
    failed: int


@dataclass(frozen=True)
class Explanation:
    """« Pourquoi ? » (scenario 7) : la regle, les faits et chaque decision prise."""

    module: str
    name: str
    rule: str
    facts: list[dict[str, Any]]
    status: str
    outcome: str | None
    created_at: datetime
    interventions: list[InterventionView]


async def explain(session: AsyncSession, signal_id: uuid.UUID) -> Explanation | None:
    row = await session.scalar(select(SignalRow).where(SignalRow.id == signal_id))
    if row is None:
        return None
    decisions = await session.scalars(
        select(InterventionRow)
        .where(InterventionRow.signal_id == signal_id)
        .order_by(InterventionRow.level)
    )
    return Explanation(
        module=row.module,
        name=row.name,
        rule=row.rule,
        facts=list(row.facts),
        status=row.status,
        outcome=row.outcome,
        created_at=row.created_at,
        interventions=[
            InterventionView(i.level, i.channel, i.reason, i.created_at, i.delivered, i.failed)
            for i in decisions
        ],
    )


# ----------------------------------------------------------------- appareils
@dataclass(frozen=True)
class DeviceView:
    id: uuid.UUID
    label: str
    service: str  # domaine du service de notification, jamais l'adresse complete
    created_at: datetime
    last_success_at: datetime | None


def _device(row: PushSubscriptionRow) -> DeviceView:
    return DeviceView(
        row.id, row.label, push_host(row.endpoint), row.created_at, row.last_success_at
    )


async def list_devices(session: AsyncSession) -> list[DeviceView]:
    rows = await session.scalars(
        select(PushSubscriptionRow).order_by(PushSubscriptionRow.created_at)
    )
    return [_device(row) for row in rows]


async def add_device(
    session: AsyncSession, user_id: uuid.UUID, endpoint: str, p256dh: str, auth: str, label: str
) -> DeviceView:
    """Abonne un appareil (ou met a jour ses cles s'il l'etait deja)."""
    check_endpoint(endpoint)
    load_device_key(p256dh)
    check_auth_secret(auth)
    try:
        name = clean_line(label, 60, "nom")
    except ValueError:
        raise InvalidSubscriptionError("Nom d'appareil invalide.") from None
    known = await session.scalar(
        select(PushSubscriptionRow.id).where(PushSubscriptionRow.endpoint == endpoint)
    )
    if known is None:
        count = await session.scalar(select(func.count()).select_from(PushSubscriptionRow))
        if (count or 0) >= MAX_DEVICES:
            raise TooManyDevicesError
    row = await session.scalar(
        insert(PushSubscriptionRow)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            label=name,
        )
        .on_conflict_do_update(
            constraint="uq_core_push_subscriptions_user_id_endpoint",
            set_={"p256dh": p256dh, "auth": auth, "label": name, "failures": 0},
        )
        .returning(PushSubscriptionRow)
    )
    if row is None:  # impossible : l'insertion ou la mise a jour rend toujours la ligne
        raise RuntimeError("abonnement non enregistre")
    return _device(row)


async def remove_device(session: AsyncSession, device_id: uuid.UUID) -> bool:
    row = await session.scalar(
        select(PushSubscriptionRow).where(PushSubscriptionRow.id == device_id)
    )
    if row is None:
        return False
    await session.delete(row)
    return True


async def request_test(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> bool:
    """Notification de test vers tous les appareils, par le meme chemin que les vraies
    (job du worker). Une par minute au plus ; False s'il n'y a aucun appareil."""
    if not await session.scalar(select(func.count()).select_from(PushSubscriptionRow)):
        return False
    await emit(
        session,
        user_id,
        "core",
        SignalDraft(
            name=TEST_SIGNAL,
            kind="scheduled",
            strength=0,
            data_class="public",
            dedup_key=f"{TEST_SIGNAL}:{now:%Y%m%dT%H%M}",
            title="Notification de test",
            body="Si tu lis ceci, les notifications de Lorakus arrivent sur cet appareil.",
            rule="Demandée depuis la page Notifications.",
            url="/notifications",
            not_before=now,
            expires_at=now + TEST_LIFETIME,
        ),
    )
    return True
