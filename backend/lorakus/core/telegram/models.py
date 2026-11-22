"""Tables du bot Telegram (migration 0019). RLS forcee.

- `core_telegram_links` : le compte Telegram (discussion privee) lie a un utilisateur ; un par
  utilisateur, une discussion ne sert qu'un utilisateur. `notify` : recevoir aussi les rappels
  par Telegram (sans detail).
- `core_telegram_codes` : le code de liaison en attente (un par utilisateur), seulement son
  empreinte SHA-256, valable 10 minutes, a usage unique.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class TelegramLink(Base):
    __tablename__ = "core_telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    notify: Mapped[bool] = mapped_column(Boolean, server_default="false")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramCode(Base):
    __tablename__ = "core_telegram_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    code_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
