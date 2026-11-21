"""core: cadre du jour, origine des durees et temps reel ; fin des preferences fixes

Revision ID: 0015_core_planning_days
Revises: 0014_core_planning_prefs
Create Date: 2026-11-21

Retour d'usage de la PR 48 : des horaires fixes ne decrivent pas une vie ou l'on mange a
18 h un jour et a 22 h le lendemain. Les preferences fixes disparaissent (table supprimee,
avec l'accord de l'utilisateur : elle ne contenait que des essais) ; le planificateur lit a
la place le cadre que l'utilisateur donne pour UN jour.

- core_planning_days : une ligne par utilisateur et par jour local. Soit un jour sans
  travail (`off`), soit une plage de travail en instants UTC (elle peut passer minuit, 20 h
  au plus) et ses pauses (repas, sport...), un tableau JSON valide par le code.
- core_tasks.estimate_source : qui a donne la duree estimee (l'utilisateur, ou Lorakus
  avec son accord) ; present si et seulement si la duree l'est. Les durees existantes
  viennent de l'utilisateur.
- core_tasks.actual_minutes : le temps reellement passe, donne a la fin d'une tache. Les
  durees et les temps reels serviront a mesurer l'ecart entre prevu et reel.

RLS forcee. Contraintes ecrites pour ne jamais valoir NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_core_planning_days"
down_revision: str | Sequence[str] | None = "0014_core_planning_prefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DAYS = "core_planning_days"
_PREFS = "core_planning_preferences"
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


def _owner_only(table: str) -> None:
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


def upgrade() -> None:
    op.drop_table(_PREFS, schema="lorakus")

    op.create_table(
        _DAYS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("off", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "breaks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _user_fk(_DAYS),
        sa.PrimaryKeyConstraint("user_id", "day", name=f"pk_{_DAYS}"),
        sa.CheckConstraint(
            "(off AND starts_at IS NULL AND ends_at IS NULL AND breaks = '[]'::jsonb) "
            "OR (NOT off AND starts_at IS NOT NULL AND ends_at IS NOT NULL "
            "AND ends_at > starts_at AND ends_at - starts_at <= interval '20 hours')",
            name="frame",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(breaks) = 'array' AND jsonb_array_length(breaks) <= 6",
            name="breaks",
        ),
        sa.CheckConstraint(_SOURCE, name="source"),
        schema="lorakus",
    )
    _owner_only(_DAYS)

    op.add_column(
        "core_tasks", sa.Column("estimate_source", sa.Text(), nullable=True), schema="lorakus"
    )
    op.add_column(
        "core_tasks", sa.Column("actual_minutes", sa.Integer(), nullable=True), schema="lorakus"
    )
    op.execute(
        "UPDATE lorakus.core_tasks SET estimate_source = 'user' WHERE estimate_minutes IS NOT NULL"
    )
    op.create_check_constraint(
        "estimate_source",
        "core_tasks",
        "(estimate_minutes IS NULL) = (estimate_source IS NULL) "
        "AND (estimate_source IS NULL OR estimate_source IN ('user', 'assistant'))",
        schema="lorakus",
    )
    op.create_check_constraint(
        "actual_minutes",
        "core_tasks",
        "actual_minutes IS NULL OR (status = 'done' AND actual_minutes BETWEEN 1 AND 10080)",
        schema="lorakus",
    )


def downgrade() -> None:
    op.drop_constraint("ck_core_tasks_actual_minutes", "core_tasks", schema="lorakus")
    op.drop_constraint("ck_core_tasks_estimate_source", "core_tasks", schema="lorakus")
    op.drop_column("core_tasks", "actual_minutes", schema="lorakus")
    op.drop_column("core_tasks", "estimate_source", schema="lorakus")
    op.drop_table(_DAYS, schema="lorakus")

    # La table de la PR 48 revient vide : ses lignes ne sont pas restaurees.
    op.create_table(
        _PREFS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _user_fk(_PREFS),
        sa.PrimaryKeyConstraint("user_id", "key", name=f"pk_{_PREFS}"),
        sa.CheckConstraint(
            "key IN ('work_start', 'work_end', 'lunch', 'dinner', 'rest_days', 'daily_cap')",
            name="key",
        ),
        sa.CheckConstraint("jsonb_typeof(value) = 'object'", name="value"),
        sa.CheckConstraint(_SOURCE, name="source"),
        schema="lorakus",
    )
    _owner_only(_PREFS)
