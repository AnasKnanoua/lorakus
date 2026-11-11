"""Trace des appels aux specialistes (migration 0006), en ajout seul."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, Integer, Numeric, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class AgentRun(Base):
    __tablename__ = "core_agent_runs"
    __table_args__ = (Index("ix_core_agent_runs_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    specialist: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_eur: Mapped[Decimal] = mapped_column(Numeric(10, 5), server_default="0")
    data_classes_sent: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
