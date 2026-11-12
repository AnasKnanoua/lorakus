"""Compteurs des limites de debit par utilisateur (migration 0008)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class RateLimitCounter(Base):
    """Nombre de requetes d'un utilisateur dans une fenetre fixe d'un compteur (bucket)."""

    __tablename__ = "core_rate_limits"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer)
