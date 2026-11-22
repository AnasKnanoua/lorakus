"""Table des preparations (migration 0018, ADR 0028). RLS forcee.

Une preparation par module, par type et par jour (unique) : jamais deux briefings pour un
jour. `sections` : des titres et des lignes de texte, ecrits par le code du module.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class PreparationRow(Base):
    __tablename__ = "core_preparations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "module", "kind", "day", name="uq_core_preparations_user_id_module_kind_day"
        ),
        Index("ix_core_preparations_user_id_expires_at", "user_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    module: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)  # « briefing »
    day: Mapped[date] = mapped_column(Date)  # le jour prepare
    title: Mapped[str] = mapped_column(Text)
    sections: Mapped[Any] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="ready")  # ready | consulted
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consulted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
