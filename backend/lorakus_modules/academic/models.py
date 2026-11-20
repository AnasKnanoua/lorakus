"""Tables du module academic (migration academic_0001). RLS forcee.

Le module garde le sens metier (cours, devoir ou examen, coefficient) ; la tache qui en
decoule vit dans le planning du Core (`core_tasks`, `owner_module = academic`,
`owner_ref` = identifiant de l'evaluation) et n'est jamais lue ici directement : seulement
par le port `ModuleTasks` (ADR 0018).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class Course(Base):
    """Un cours. `name_key` (sans casse ni accents) refuse deux cours de meme nom."""

    __tablename__ = "acad_courses"
    __table_args__ = (
        # Cible de la cle composee des evaluations : meme utilisateur que le cours.
        UniqueConstraint("id", "user_id", name="uq_acad_courses_id_user_id"),
        UniqueConstraint("user_id", "name_key", name="uq_acad_courses_user_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    name_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Assessment(Base):
    """Une evaluation : devoir a rendre ou examen, avec son echeance (un jour local)."""

    __tablename__ = "acad_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["course_id", "user_id"],
            ["acad_courses.id", "acad_courses.user_id"],
            name="fk_acad_assessments_course_id_acad_courses",
            ondelete="CASCADE",
        ),
        Index("ix_acad_assessments_user_id_status_due_on", "user_id", "status", "due_on"),
        Index("ix_acad_assessments_course_id", "course_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    course_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    due_on: Mapped[date] = mapped_column(Date)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    # Provenance (ADR 0015) : saisie dans la page, ou carte confirmee d'une conversation.
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
