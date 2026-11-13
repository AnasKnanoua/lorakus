"""Tables de la memoire (migration 0009). RLS forcee : chacun ne voit que ses faits."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class MemoryFact(Base):
    """Un fait sur l'utilisateur, avec sa provenance (ADR 0015)."""

    __tablename__ = "core_memory_facts"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_core_memory_facts_user_content"),
        Index("ix_core_memory_facts_user_id_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary)
    category: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    data_class: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_constraints: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryRejection(Base):
    """Empreinte d'un fait refuse : jamais repropose, et son texte n'est pas garde."""

    __tablename__ = "core_memory_rejections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemorySettings(Base):
    """Reglages de la memoire par utilisateur (absents = valeurs par defaut)."""

    __tablename__ = "core_memory_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    propose_after_conversations: Mapped[bool] = mapped_column(Boolean, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
