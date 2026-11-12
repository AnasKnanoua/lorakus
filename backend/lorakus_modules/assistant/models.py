"""Tables du module Assistant : conversations et messages (classe personal, RLS forcee)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class AssistantConversation(Base):
    """Une conversation, titree par son premier message (sans appel IA)."""

    __tablename__ = "asst_conversations"
    __table_args__ = (
        Index("ix_asst_conversations_user_id_updated_at", "user_id", "updated_at"),
        UniqueConstraint("id", "user_id", name="uq_asst_conversations_id_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantMessage(Base):
    """Un message. status : ok, interrupted (reponse coupee), fallback (gabarit, pas d'IA)."""

    __tablename__ = "asst_messages"
    __table_args__ = (
        Index("ix_asst_messages_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_asst_messages_user_id", "user_id"),
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["asst_conversations.id", "asst_conversations.user_id"],
            name="fk_asst_messages_conversation_id_asst_conversations",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
