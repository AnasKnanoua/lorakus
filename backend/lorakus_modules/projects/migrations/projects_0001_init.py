"""projects: boite d'idees, projets et leurs taches

Revision ID: projects_0001
Revises:
Create Date: 2026-11-21

Branche Alembic du module : elle ne depend que du Core (core_users, et le planning dont le
module utilise les taches). Classe personal. RLS forcee. Contraintes nommees court (la
convention de nommage ajoute deja le prefixe ck_<table>_) et ecrites pour ne jamais valoir
NULL.

- proj_ideas : texte d'une ligne (500 caracteres), dans la boite ou archivee.
- proj_projects : nom unique par utilisateur (name_key : sans casse ni accents), actif ou
  termine ; finished_at present si et seulement si termine.
- proj_tasks : tache d'un projet, par une cle composee (project_id, user_id) : elle
  appartient forcement au proprietaire du projet.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "projects_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("projects",)
depends_on: str | Sequence[str] | None = "0016_core_task_steps"

_TABLES = ("proj_ideas", "proj_projects", "proj_tasks")
_TS = sa.DateTime(timezone=True)
_SOURCE = (
    "source_kind IN ('user', 'conversation') "
    "AND (source_kind = 'conversation') = (source_ref IS NOT NULL) "
    "AND (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200)"
)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["lorakus.core_users.id"],
        name=f"fk_{table}_user_id_core_users",
        ondelete="CASCADE",
    )


def _now(name: str) -> sa.Column[object]:
    return sa.Column(name, _TS, server_default=sa.func.now(), nullable=False)


def _source() -> list[sa.Column[object]]:
    return [
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "proj_ideas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="inbox", nullable=False),
        *_source(),
        _now("created_at"),
        sa.Column("archived_at", _TS, nullable=True),
        _user_fk("proj_ideas"),
        sa.PrimaryKeyConstraint("id", name="pk_proj_ideas"),
        sa.CheckConstraint("char_length(text) BETWEEN 1 AND 500", name="text"),
        sa.CheckConstraint(
            "(status = 'inbox' AND archived_at IS NULL) "
            "OR (status = 'archived' AND archived_at IS NOT NULL)",
            name="status",
        ),
        sa.CheckConstraint(_SOURCE, name="source"),
        schema="lorakus",
    )
    op.create_index(
        "ix_proj_ideas_user_id_status", "proj_ideas", ["user_id", "status"], schema="lorakus"
    )

    op.create_table(
        "proj_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        *_source(),
        _now("created_at"),
        _now("last_activity_at"),
        sa.Column("finished_at", _TS, nullable=True),
        _user_fk("proj_projects"),
        sa.PrimaryKeyConstraint("id", name="pk_proj_projects"),
        sa.UniqueConstraint("id", "user_id", name="uq_proj_projects_id_user_id"),
        sa.UniqueConstraint("user_id", "name_key", name="uq_proj_projects_user_id_name_key"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name"),
        sa.CheckConstraint("char_length(name_key) BETWEEN 1 AND 200", name="name_key"),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) BETWEEN 1 AND 500",
            name="description",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND finished_at IS NULL) "
            "OR (status = 'done' AND finished_at IS NOT NULL)",
            name="status",
        ),
        sa.CheckConstraint(_SOURCE, name="source"),
        schema="lorakus",
    )

    op.create_table(
        "proj_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        *_source(),
        _now("created_at"),
        sa.Column("completed_at", _TS, nullable=True),
        _user_fk("proj_tasks"),
        sa.PrimaryKeyConstraint("id", name="pk_proj_tasks"),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["lorakus.proj_projects.id", "lorakus.proj_projects.user_id"],
            name="fk_proj_tasks_project_id_proj_projects",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 110", name="title"),
        sa.CheckConstraint(
            "(status = 'open' AND completed_at IS NULL) "
            "OR (status = 'done' AND completed_at IS NOT NULL)",
            name="status",
        ),
        sa.CheckConstraint(_SOURCE, name="source"),
        schema="lorakus",
    )
    op.create_index("ix_proj_tasks_project_id", "proj_tasks", ["project_id"], schema="lorakus")

    for table in _TABLES:
        op.execute(f"ALTER TABLE lorakus.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lorakus.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_migrator ON lorakus.{table} TO lorakus_migrator "
            "USING (true) WITH CHECK (true)"
        )
        op.execute(
            f"CREATE POLICY {table}_owner_only ON lorakus.{table} TO lorakus_app "
            "USING (user_id = lorakus.current_user_id()) "
            "WITH CHECK (user_id = lorakus.current_user_id())"
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table, schema="lorakus")
