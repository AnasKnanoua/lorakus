"""Messages recus par le bot (P5, PR 54, scenario 5).

Regles, dans l'ordre :
- seules les discussions privees comptent ; les groupes, les canaux et les autres bots sont
  ignores sans reponse ;
- un code de liaison (« /start K7QM-2XPH », ou le code seul) lie la discussion au compte qui
  l'a demande ; 5 codes faux par discussion et par heure, puis plus aucune tentative ;
- une discussion non liee recoit une seule explication (comment lier), rien d'autre ;
- une discussion liee : « /aide » explique, tout autre texte devient une idee (capture du
  module qui la declare, aujourd'hui projects), sous la RLS de l'utilisateur.

Aucun modele de langage ici : le texte est range tel quel (une ligne, 500 caracteres) et ne
sera montre au modele qu'a travers inert(). Rien de ce qu'il contient ne declenche quoi que ce
soit : ce n'est jamais une commande, seulement une idee.
"""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol

import structlog
from prometheus_client import Counter, Gauge
from sqlalchemy import select

from lorakus.core.capture import Capture, CaptureRefusedError, CaptureRequest
from lorakus.core.modules.models import UserModule
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.outbound import OutboundError
from lorakus.core.telegram.bot import TelegramError, Update
from lorakus.core.telegram.service import link_chat, touch, user_for_chat
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.telegram")

# « /start K7QM-2XPH », « /start@LorakusBot K7QM2XPH », ou le code seul.
CODE: Final = re.compile(
    r"^(?:/start(?:@\w+)?\s+)?([A-Za-z0-9]{4})[-\s]?([A-Za-z0-9]{4})$", re.ASCII
)
COMMAND: Final = re.compile(r"^/(\w+)(?:@\w+)?(?:\s|$)", re.ASCII)
MAX_CODE_ATTEMPTS: Final = 5
ATTEMPT_WINDOW_S: Final = 3600

HELP: Final = (
    "Envoie-moi une idée, en un message : je la range dans ta boîte à idées de Lorakus. "
    "Les rappels peuvent aussi arriver ici, sans aucun détail, si tu l'as choisi dans "
    "Lorakus (page Notifications)."
)
LINKED: Final = "C'est fait : ce compte Telegram est lié à Lorakus. " + HELP
BAD_CODE: Final = (
    "Ce code est invalide ou expiré. Crée-en un nouveau dans Lorakus, page Notifications."
)
NOT_LINKED: Final = (
    "Ce compte Telegram n'est lié à aucun compte Lorakus. Pour le lier : page Notifications, "
    "« Lier Telegram », puis envoie-moi le code."
)
TEXT_ONLY: Final = "Je ne garde que le texte pour l'instant : envoie ton idée en un message."
UNKNOWN_COMMAND: Final = "Commande inconnue. Envoie /aide."
NO_BOX: Final = "La boîte à idées est désactivée (module Projets) : rien n'a été noté."
FAILED: Final = "Je n'ai pas pu noter ton idée. Réessaie dans un instant."

UPDATES = Counter(
    "lorakus_telegram_updates_total", "Messages recus par le bot, par issue", ["outcome"]
)
CONFIGURED = Gauge(
    "lorakus_telegram_configured", "1 si le worker a un jeton de bot (la releve doit tourner)"
)
LAST_POLL = Gauge(
    "lorakus_telegram_poll_last_success_timestamp_seconds", "Dernier releve reussi du bot"
)


class Sender(Protocol):
    async def send(self, chat_id: int, message: str) -> None: ...


class Poller(Sender, Protocol):
    async def updates(self, offset: int | None, wait_s: int) -> list[Update]: ...


@dataclass
class Attempts:
    """Codes faux par discussion (memoire du worker) : ralentit qui devinerait un code."""

    window_s: int = ATTEMPT_WINDOW_S
    clock: Callable[[], float] = time.monotonic
    _seen: dict[int, list[float]] = field(default_factory=dict[int, list[float]])

    def blocked(self, chat_id: int) -> bool:
        now = self.clock()
        recent = [t for t in self._seen.get(chat_id, []) if now - t < self.window_s]
        self._seen[chat_id] = recent
        return len(recent) >= MAX_CODE_ATTEMPTS

    def failed(self, chat_id: int) -> None:
        self._seen.setdefault(chat_id, []).append(self.clock())


async def _capture(
    database: Database, registry: ModuleRegistry, user: uuid.UUID, text: str, now: datetime
) -> str:
    manifest = registry.capturing()
    async with database.transaction(user) as session:
        await touch(session, now)
        capture: Capture | None = manifest.capture if manifest is not None else None
        if manifest is None or capture is None:
            return NO_BOX
        enabled = await session.scalar(
            select(UserModule.enabled).where(UserModule.module_id == manifest.id)
        )
        if not enabled:
            return NO_BOX
        try:  # un refus arrive avant toute ecriture : la releve (touch) reste enregistree
            return await capture(CaptureRequest(session, user, text, "telegram"))
        except CaptureRefusedError as refused:
            return str(refused)


async def handle(
    database: Database,
    registry: ModuleRegistry,
    attempts: Attempts,
    update: Update,
    now: datetime,
) -> tuple[str, str | None]:
    """(issue, reponse a envoyer ou None)."""
    if update.chat_id is None or not update.private or update.from_bot:
        return "ignored", None
    chat = update.chat_id
    text = (update.text or "").strip()
    code = CODE.fullmatch(text)
    if code is not None and not attempts.blocked(chat):
        user = await link_chat(database, code.group(1) + code.group(2), chat, now)
        if user is not None:
            return "linked", LINKED
        attempts.failed(chat)
        # Un texte de 8 caracteres peut aussi etre une idee : seulement si le compte est lie.
        if await user_for_chat(database, chat) is None:
            return "bad_code", BAD_CODE
    user = await user_for_chat(database, chat)
    if user is None:
        if code is not None:
            return "blocked", None  # trop de codes faux : plus de reponse
        return "not_linked", NOT_LINKED
    if not text:
        return "not_text", TEXT_ONLY
    command = COMMAND.match(text)
    if command is not None:
        name = command.group(1).lower()
        if name in ("aide", "help", "start"):
            return "help", HELP
        return "unknown_command", UNKNOWN_COMMAND
    try:
        return "captured", await _capture(database, registry, user, text, now)
    except Exception:
        log.exception("telegram_capture_crashed")
        return "crashed", FAILED


@dataclass
class PollState:
    """Ce que le worker garde entre deux releves : le prochain numero a demander (les
    precedents sont alors acquittes par Telegram) et les tentatives de code."""

    offset: int | None = None
    attempts: Attempts = field(default_factory=Attempts)


async def poll_round(
    database: Database,
    bot: Poller,
    registry: ModuleRegistry,
    state: PollState,
    now: Callable[[], datetime],
    budget_s: float = 45.0,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, int]:
    """Releve et traite les messages pendant `budget_s` secondes au plus (le job tourne chaque
    minute : jamais deux releves en meme temps, sinon Telegram refuse le second)."""
    counts: dict[str, int] = {}
    deadline = clock() + budget_s
    while True:
        remaining = deadline - clock()
        if remaining < 12:
            break
        try:
            updates = await bot.updates(state.offset, int(min(20, remaining - 10)))
        except (OutboundError, TelegramError) as error:
            reason = error.reason
            log.warning("telegram_poll_failed", reason=reason)
            counts[f"poll_{reason}"] = counts.get(f"poll_{reason}", 0) + 1
            break
        LAST_POLL.set_to_current_time()
        for update in updates:
            # Avance d'abord : un message qui ferait echouer le traitement n'est pas rejoue
            # sans fin. Un message traite deux fois (redemarrage) donnerait au pire « deja
            # dans ta boite ».
            state.offset = update.update_id + 1
            outcome, reply = await handle(database, registry, state.attempts, update, now())
            UPDATES.labels(outcome=outcome).inc()
            counts[outcome] = counts.get(outcome, 0) + 1
            if reply is not None and update.chat_id is not None:
                try:
                    await bot.send(update.chat_id, reply)
                except (OutboundError, TelegramError) as error:
                    log.warning("telegram_reply_failed", reason=error.reason)
    return counts
