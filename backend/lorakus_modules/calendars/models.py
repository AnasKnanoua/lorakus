"""Tables du module calendars (migration calendars_0001). RLS forcee."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class Subscription(Base):
    """Abonnement a un calendrier ICS. L'adresse est un SECRET (elle donne acces a tout le
    calendrier) : chiffree, jamais reaffichee en entier, jamais journalisee."""

    __tablename__ = "cal_subscriptions"
    __table_args__ = (
        Index("ix_cal_subscriptions_user_id", "user_id"),
        Index("ix_cal_subscriptions_next_sync_at", "next_sync_at"),
        UniqueConstraint("user_id", "url_digest", name="uq_cal_subscriptions_user_id_url_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    # AES-256-GCM, cle des connecteurs, liee a (utilisateur, abonnement).
    url_ciphertext: Mapped[str] = mapped_column(Text)
    # Empreinte de l'adresse normalisee : refuse un doublon sans dechiffrer.
    url_digest: Mapped[bytes] = mapped_column(LargeBinary)
    url_hint: Mapped[str] = mapped_column(Text)  # domaine seul, ex. calendar.google.com/…
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_status: Mapped[int | None] = mapped_column(SmallInteger)
    entries_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, server_default="0")
    truncated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
