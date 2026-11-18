"""Tables du planning (migration 0013). RLS forcee : chacun ne voit que ses lignes.

Generiques (ADR 0018) : une tache ne connait ni devoir ni projet. `owner_module` et
`owner_ref` disent quel module l'a creee et a quel objet elle correspond ; nuls pour une
tache personnelle. L'agenda ne contient que des creneaux concrets, sans regle de
repetition : `calendars` deplie les recurrences avant de les y ecrire.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class Task(Base):
    """Une tache ; `parent_id` en fait une sous-tache (un seul niveau)."""

    __tablename__ = "core_tasks"
    __table_args__ = (
        # Cible de la cle composee des sous-taches : un parent appartient au meme utilisateur.
        UniqueConstraint("id", "user_id", name="uq_core_tasks_id_user_id"),
        ForeignKeyConstraint(
            ["parent_id", "user_id"],
            ["core_tasks.id", "core_tasks.user_id"],
            name="fk_core_tasks_parent_id_core_tasks",
            ondelete="CASCADE",
        ),
        Index("ix_core_tasks_user_id_status_due_on", "user_id", "status", "due_on"),
        Index("ix_core_tasks_parent_id", "parent_id"),
        Index(
            "uq_core_tasks_owner",
            "user_id",
            "owner_module",
            "owner_ref",
            unique=True,
            postgresql_where=text("owner_module IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    # Echeance : un jour local (« pour vendredi »), rendu en fin de journee chez l'utilisateur.
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgendaEntry(Base):
    """Un creneau : horaire (starts_at, ends_at en UTC) ou journee entiere (dates locales).

    Ecrit par un module (`owner_module`, `source_key` : par exemple un abonnement ICS,
    `external_key` : l'occurrence) ; une resynchronisation remplace les creneaux de sa source.
    """

    __tablename__ = "core_agenda_entries"
    __table_args__ = (
        Index("ix_core_agenda_entries_user_id_starts_at", "user_id", "starts_at"),
        Index("ix_core_agenda_entries_user_id_start_date", "user_id", "start_date"),
        Index(
            "uq_core_agenda_entries_source",
            "user_id",
            "owner_module",
            "source_key",
            "external_key",
            unique=True,
            postgresql_where=text("owner_module IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Journee entiere : dates locales, fin exclue (comme ICS) ; jamais converties de fuseau.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
