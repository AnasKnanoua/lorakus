"""Abonnements ICS et synchronisation vers l'agenda du Core (PR 45, ADR 0041).

- L'adresse d'un abonnement est un SECRET (une adresse ICS « privee » de Google donne tout le
  calendrier a qui la connait) : chiffree par la cle des connecteurs, liee a l'utilisateur et
  a l'abonnement, jamais renvoyee par l'API ni journalisee ; l'interface n'en montre que le
  domaine.
- Un seul job (`calendars.sync`, chaque minute) traite tout ce qui est du, pour tous les
  utilisateurs (MODULE_SYSTEM.md §11) : `cal_claim_due` reserve des abonnements, chacun est
  ensuite lu et ecrit sous la RLS de son utilisateur.
- Telechargement par le client sortant du Core (SSRF), lecture et depliage dans un fil a part
  avec un delai, ecriture par `ModuleAgenda.replace_source` : rejouer donne le meme agenda.
- Un echec garde les creneaux deja connus et repousse l'essai suivant (30 min, puis le double,
  24 h au plus).
"""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import anyio
import anyio.to_thread
import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.service import user_timezone
from lorakus.core.identity.crypto import FieldCipher
from lorakus.core.outbound import (
    FetchLimits,
    InvalidUrlError,
    OutboundError,
    OutboundHttp,
    display_hint,
    parse_public_url,
)
from lorakus.core.outbound.client import MESSAGES as OUTBOUND_MESSAGES
from lorakus.core.planning.service import InvalidAgendaEntryError, ModuleAgenda
from lorakus.db.database import Database
from lorakus_modules.calendars.ics import InvalidCalendarError, ParsedCalendar, parse_calendar
from lorakus_modules.calendars.models import Subscription

log = structlog.get_logger("lorakus.calendars")

MODULE_ID: Final = "calendars"
AGENDA: Final = ModuleAgenda(MODULE_ID)
MAX_SUBSCRIPTIONS: Final = 20
MAX_NAME_CHARS: Final = 80
SYNC_INTERVAL: Final = timedelta(minutes=30)
MAX_BACKOFF: Final = timedelta(hours=24)
LEASE: Final = timedelta(minutes=10)
CLAIM_BATCH: Final = 10
WINDOW_PAST: Final = timedelta(days=7)
WINDOW_FUTURE: Final = timedelta(days=120)
PARSE_TIMEOUT_S: Final = 30.0
FETCH: Final = FetchLimits(max_bytes=4 * 1024 * 1024)
ACCEPT: Final = "text/calendar, text/plain;q=0.5, */*;q=0.1"

# Messages des erreurs de synchronisation (tutoiement, sans detail technique).
ERROR_MESSAGES: Final[dict[str, str]] = {
    **OUTBOUND_MESSAGES,
    "not_calendar": "Le serveur n'a pas renvoyé un calendrier (ICS). Vérifie l'adresse.",
    "unreadable": "Le calendrier est illisible.",
    "too_many_events": "Le calendrier contient trop d'événements.",
    "too_slow": "Le calendrier est trop long à lire.",
    "rejected_entries": "Certains événements du calendrier sont invalides.",
    "secret_unreadable": "L'adresse enregistrée est illisible : supprime l'abonnement et "
    "ajoute-le de nouveau.",
}


class SubscriptionError(Exception):
    """Refus lisible par l'utilisateur (message en francais)."""


class SubscriptionNotFoundError(Exception):
    """Abonnement absent ou d'un autre utilisateur (la RLS les confond)."""


@dataclass(frozen=True)
class SubscriptionView:
    id: uuid.UUID
    name: str
    hint: str
    status: str
    error: str | None
    entries_count: int
    skipped_count: int
    truncated: bool
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_sync_at: datetime
    created_at: datetime


def error_message(code: str | None, status: int | None) -> str | None:
    if code is None:
        return None
    if code == "http_status" and status is not None:
        return f"Le serveur a refusé la demande (code {status})."
    return ERROR_MESSAGES.get(code, "La synchronisation a échoué.")


def _view(row: Subscription) -> SubscriptionView:
    return SubscriptionView(
        id=row.id,
        name=row.name,
        hint=row.url_hint,
        status=row.status,
        error=error_message(row.error_code, row.error_status),
        entries_count=row.entries_count,
        skipped_count=row.skipped_count,
        truncated=row.truncated,
        last_attempt_at=row.last_attempt_at,
        last_success_at=row.last_success_at,
        next_sync_at=row.next_sync_at,
        created_at=row.created_at,
    )


def _secret_context(user_id: uuid.UUID, subscription_id: uuid.UUID) -> bytes:
    """Le chiffre ne vaut que pour CET abonnement de CET utilisateur (copie inutilisable)."""
    return f"calendars:{user_id}:{subscription_id}".encode()


def _clean_name(name: str) -> str:
    value = " ".join("".join(" " if not c.isprintable() else c for c in name).split())
    if not value:
        raise SubscriptionError("Donne un nom à ce calendrier.")
    if len(value) > MAX_NAME_CHARS:
        raise SubscriptionError(f"Nom trop long ({MAX_NAME_CHARS} caractères au plus).")
    return value


# ------------------------------------------------------------- abonnements
async def list_subscriptions(session: AsyncSession) -> list[SubscriptionView]:
    rows = await session.scalars(select(Subscription).order_by(Subscription.created_at))
    return [_view(r) for r in rows]


async def _get(session: AsyncSession, subscription_id: uuid.UUID) -> Subscription:
    row = await session.get(Subscription, subscription_id, with_for_update=True)
    if row is None:
        raise SubscriptionNotFoundError(subscription_id)
    return row


async def add_subscription(
    session: AsyncSession,
    cipher: FieldCipher,
    user_id: uuid.UUID,
    name: str,
    raw_url: str,
) -> SubscriptionView:
    """Valide l'adresse (sans reseau), la chiffre et programme une synchronisation immediate.

    L'API ne telecharge rien : seul le worker parle a l'exterieur (un clic ne declenche
    aucune requete sortante depuis le processus expose a Internet)."""
    label = _clean_name(name)
    try:
        url = parse_public_url(raw_url.strip())
    except InvalidUrlError as error:
        raise SubscriptionError(f"Adresse refusée : {error}.") from None
    count = await session.scalar(select(func.count()).select_from(Subscription))
    if (count or 0) >= MAX_SUBSCRIPTIONS:
        raise SubscriptionError(f"{MAX_SUBSCRIPTIONS} calendriers au plus.")
    digest = hashlib.sha256(url.text.encode()).digest()
    if await session.scalar(select(Subscription.id).where(Subscription.url_digest == digest)):
        raise SubscriptionError("Tu es déjà abonné à ce calendrier.")
    subscription_id = uuid.uuid4()
    row = Subscription(
        id=subscription_id,
        user_id=user_id,
        name=label,
        url_ciphertext=cipher.encrypt(url.text.encode(), _secret_context(user_id, subscription_id)),
        url_digest=digest,
        url_hint=display_hint(url),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _view(row)


async def delete_subscription(session: AsyncSession, subscription_id: uuid.UUID) -> int:
    """Supprime l'abonnement ET ses creneaux ; rend le nombre de creneaux retires."""
    row = await _get(session, subscription_id)
    removed = await AGENDA.clear_source(session, str(row.id))
    await session.execute(delete(Subscription).where(Subscription.id == row.id))
    return removed


async def request_sync(session: AsyncSession, subscription_id: uuid.UUID) -> SubscriptionView:
    """« Synchroniser maintenant » : le job de la minute suivante s'en charge."""
    row = await _get(session, subscription_id)
    row.next_sync_at = datetime.now(UTC)
    row.failures = 0
    await session.flush()
    await session.refresh(row)
    return _view(row)


# ---------------------------------------------------------- synchronisation
def backoff(failures: int) -> timedelta:
    """Attente apres `failures` echecs consecutifs : 30 min, 1 h, 2 h... 24 h au plus.

    L'exposant est borne : un calendrier en panne depuis des semaines accumule les echecs, et
    2 ** 50 fois 30 minutes depasse ce que timedelta peut representer (OverflowError)."""
    return min(SYNC_INTERVAL * (2 ** min(max(0, failures - 1), 6)), MAX_BACKOFF)


async def _record_failure(
    database: Database,
    user_id: uuid.UUID,
    subscription_id: uuid.UUID,
    now: datetime,
    code: str,
    status: int | None = None,
) -> None:
    async with database.transaction(user_id) as session:
        row = await session.get(Subscription, subscription_id, with_for_update=True)
        if row is None:
            return
        row.failures += 1
        row.status = "error"
        row.error_code = code
        row.error_status = status if code == "http_status" else None
        row.last_attempt_at = now
        row.next_sync_at = now + backoff(row.failures)
        row.locked_until = None
        row.updated_at = now
    log.info("calendar_sync_failed", subscription=str(subscription_id), reason=code)


async def _parse(body: bytes, now: datetime, tz: ZoneInfo) -> ParsedCalendar:
    """Lecture dans un fil a part (le worker continue de tourner), bornee dans le temps."""
    with anyio.fail_after(PARSE_TIMEOUT_S):
        return await anyio.to_thread.run_sync(
            parse_calendar,
            body,
            now - WINDOW_PAST,
            now + WINDOW_FUTURE,
            tz,
            abandon_on_cancel=True,
        )


async def sync_subscription(
    database: Database,
    cipher: FieldCipher,
    http: OutboundHttp,
    subscription_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime,
) -> str:
    """Synchronise un abonnement ; rend l'issue (« ok » ou le code d'erreur)."""
    async with database.transaction(user_id) as session:
        row = await session.get(Subscription, subscription_id)
        if row is None:
            return "gone"
        ciphertext = row.url_ciphertext
        tz = await user_timezone(session)
    try:
        url = cipher.decrypt(ciphertext, _secret_context(user_id, subscription_id)).decode()
    except (ValueError, UnicodeDecodeError):
        await _record_failure(database, user_id, subscription_id, now, "secret_unreadable")
        return "secret_unreadable"
    try:
        fetched = await http.get(url, limits=FETCH, accept=ACCEPT)
        parsed = await _parse(fetched.body, now, tz)
    except OutboundError as error:
        await _record_failure(database, user_id, subscription_id, now, error.reason, error.status)
        return error.reason
    except TimeoutError:
        await _record_failure(database, user_id, subscription_id, now, "too_slow")
        return "too_slow"
    except InvalidCalendarError as error:
        await _record_failure(database, user_id, subscription_id, now, error.code)
        return error.code
    try:
        async with database.transaction(user_id) as session:
            row = await session.get(Subscription, subscription_id, with_for_update=True)
            if row is None:  # supprime pendant le telechargement : rien a ecrire
                return "gone"
            written = await AGENDA.replace_source(
                session, user_id, str(subscription_id), parsed.items
            )
            row.status = "ok"
            row.error_code = None
            row.error_status = None
            row.entries_count = written
            row.skipped_count = parsed.skipped
            row.truncated = parsed.truncated
            row.failures = 0
            row.last_attempt_at = now
            row.last_success_at = now
            row.next_sync_at = now + SYNC_INTERVAL
            row.locked_until = None
            row.updated_at = now
    except InvalidAgendaEntryError:
        await _record_failure(database, user_id, subscription_id, now, "rejected_entries")
        return "rejected_entries"
    log.info(
        "calendar_synced",
        subscription=str(subscription_id),
        host=fetched.host,
        entries=written,
        skipped=parsed.skipped,
    )
    return "ok"


async def claim_due(
    database: Database, limit: int = CLAIM_BATCH
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(abonnement, utilisateur) dus, reserves pour LEASE (fonction SECURITY DEFINER)."""
    async with database.transaction(None) as session:
        rows = await session.execute(
            text("SELECT id, user_id FROM lorakus.cal_claim_due(:limit, :lease)"),
            {"limit": limit, "lease": LEASE},
        )
        return [(row[0], row[1]) for row in rows]


async def sync_due(
    database: Database,
    cipher: FieldCipher,
    http: OutboundHttp,
    now: datetime,
    limit: int = CLAIM_BATCH,
) -> dict[str, int]:
    """Tout ce qui est du maintenant, pour tous les utilisateurs ; rend les issues comptees.
    Un abonnement en echec n'empeche jamais les suivants."""
    outcomes: dict[str, int] = {}
    due: Sequence[tuple[uuid.UUID, uuid.UUID]] = await claim_due(database, limit)
    for subscription_id, user_id in due:
        try:
            outcome = await sync_subscription(database, cipher, http, subscription_id, user_id, now)
        except Exception:
            log.exception("calendar_sync_crashed", subscription=str(subscription_id))
            outcome = "crashed"
            # Le bail expire seul (LEASE) : l'abonnement sera repris plus tard.
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return outcomes
