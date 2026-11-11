"""Outbox des evenements (migration 0005)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class OutboxEvent(Base):
    """Evenement a livrer. Ecrit dans la transaction qui le cause ; livre par le worker."""

    __tablename__ = "core_outbox"
    __table_args__ = (
        Index(
            "ix_core_outbox_pending",
            "next_attempt_at",
            postgresql_where=text("published_at IS NULL AND dead_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class OutboxDelivery(Base):
    """Handler deja passe pour un evenement : il n'est pas rejoue."""

    __tablename__ = "core_outbox_deliveries"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core_outbox.id", ondelete="CASCADE"), primary_key=True
    )
    handler: Mapped[str] = mapped_column(Text, primary_key=True)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
