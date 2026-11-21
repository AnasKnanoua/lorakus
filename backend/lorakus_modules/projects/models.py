"""Tables du module projects (migration projects_0001). RLS forcee.

- `proj_ideas` : la boite d'idees. Une idee se note en deux secondes ; elle reste dans la
  boite, est archivee, ou devient un projet (elle disparait alors : son texte devient la
  description du projet).
- `proj_projects` : un projet actif ou termine, avec la date de sa derniere activite (le
  projet « dort » au-dela de 14 jours sans activite).
- `proj_tasks` : les taches d'un projet. Chacune a SA tache dans le planning du Core
  (`owner_module = projects`, `owner_ref` = identifiant de la ligne), creee par le port
  `ModuleTasks` dans la meme transaction : c'est elle que voient le planificateur et le chat.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class Idea(Base):
    __tablename__ = "proj_ideas"
    __table_args__ = (Index("ix_proj_ideas_user_id_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="inbox")
    # Provenance (ADR 0015) : saisie dans la page, ou carte confirmee d'une conversation.
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "proj_projects"
    __table_args__ = (
        # Cible de la cle composee des taches : meme utilisateur que le projet.
        UniqueConstraint("id", "user_id", name="uq_proj_projects_id_user_id"),
        UniqueConstraint("user_id", "name_key", name="uq_proj_projects_user_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    name_key: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Creation, tache ajoutee ou terminee : ce qui montre que le projet avance.
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectTask(Base):
    __tablename__ = "proj_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["proj_projects.id", "proj_projects.user_id"],
            name="fk_proj_tasks_project_id_proj_projects",
            ondelete="CASCADE",
        ),
        Index("ix_proj_tasks_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
