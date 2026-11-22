"""Liaison d'un compte Telegram (P5, PR 54).

1. Dans la page Notifications, l'utilisateur demande un code (`new_code`) : 8 caracteres sans
   ambiguite (« K7QM-2XPH »), valable 10 minutes, a usage unique. Seule son empreinte SHA-256
   est gardee ; demander un autre code remplace le precedent.
2. Il envoie ce code a son bot (« /start K7QM-2XPH », ou le code seul). Le worker le consomme
   (`link_chat`, fonction SECURITY DEFINER) : la discussion privee est liee a son compte.
3. Ce qu'il envoie ensuite au bot devient une idee (capture rapide) ; s'il le choisit, les
   rappels lui arrivent aussi sur Telegram, sans aucun detail.

Les routes de l'API et le job du worker passent par ici ; tout est sous RLS, sauf les deux
fonctions qui ne rendent qu'un identifiant.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.telegram.models import TelegramCode, TelegramLink
from lorakus.db.database import Database

CODE_LIFETIME: Final = timedelta(minutes=10)
# Sans 0/O, 1/I/L : un code se recopie sans erreur.
ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final = 8


def code_hash(code: str) -> str:
    """Empreinte d'un code, quelle que soit sa forme (casse, tiret, espaces)."""
    normalized = "".join(c for c in code.upper() if c.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def display(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


@dataclass(frozen=True)
class NewCode:
    code: str  # « K7QM-2XPH »
    expires_at: datetime


async def new_code(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> NewCode:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    expires = now + CODE_LIFETIME
    await session.execute(
        insert(TelegramCode)
        .values(user_id=user_id, code_hash=code_hash(raw), expires_at=expires)
        .on_conflict_do_update(
            index_elements=[TelegramCode.user_id],
            set_={"code_hash": code_hash(raw), "expires_at": expires},
        )
    )
    return NewCode(display(raw), expires)


@dataclass(frozen=True)
class LinkView:
    notify: bool
    linked_at: datetime
    last_message_at: datetime | None


async def link_status(session: AsyncSession) -> LinkView | None:
    row = await session.scalar(select(TelegramLink))
    return None if row is None else LinkView(row.notify, row.linked_at, row.last_message_at)


async def set_notify(session: AsyncSession, notify: bool) -> bool:
    result = await session.execute(
        update(TelegramLink).values(notify=notify).returning(TelegramLink.user_id)
    )
    return result.first() is not None


async def unlink(session: AsyncSession) -> bool:
    """Delie le compte (et oublie un code en attente) ; False s'il n'etait pas lie."""
    await session.execute(delete(TelegramCode))
    result = await session.execute(delete(TelegramLink).returning(TelegramLink.user_id))
    return result.first() is not None


async def notify_chat(session: AsyncSession) -> int | None:
    """La discussion ou envoyer aussi les rappels (sans detail), si l'utilisateur l'a choisi."""
    return await session.scalar(select(TelegramLink.chat_id).where(TelegramLink.notify))


async def touch(session: AsyncSession, now: datetime) -> None:
    await session.execute(update(TelegramLink).values(last_message_at=now))


async def link_chat(database: Database, code: str, chat_id: int, now: datetime) -> uuid.UUID | None:
    """Consomme un code valide et lie la discussion ; None si le code ne vaut rien."""
    async with database.transaction(None) as session:
        found = await session.scalar(
            text("SELECT lorakus.core_telegram_link(:hash, :chat, :now)"),
            {"hash": code_hash(code), "chat": chat_id, "now": now},
        )
    return found


async def user_for_chat(database: Database, chat_id: int) -> uuid.UUID | None:
    async with database.transaction(None) as session:
        found = await session.scalar(
            text("SELECT lorakus.core_telegram_user(:chat)"), {"chat": chat_id}
        )
    return found
