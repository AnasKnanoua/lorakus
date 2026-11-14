"""Confirmations d'outils (migrations 0006 et 0012)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class ToolConfirmation(Base):
    __tablename__ = "core_tool_confirmations"
    __table_args__ = (Index("ix_core_tool_confirmations_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    tool: Mapped[str] = mapped_column(Text)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # PR 38 : annulation par l'utilisateur, et provenance de la demande (ex. conversation:<id>).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str | None] = mapped_column(Text)
