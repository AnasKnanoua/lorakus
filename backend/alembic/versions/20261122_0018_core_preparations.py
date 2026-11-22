"""core: preparations en arriere-plan, briefing du lendemain (P5, ADR 0028)

Revision ID: 0018_core_preparations
Revises: 0017_core_signals
Create Date: 2026-11-22

- core_preparations : une preparation par module, type et jour (unique : jamais deux
  briefings pour un jour), avec ses sections (titres et lignes ecrits par le code), son statut
  (ready, puis consulted, alors figee) et son expiration. RLS forcee.
- core_users_with_module : utilisateurs qui ont un module active. Un seul job par module pour
  tous les utilisateurs (MODULE_SYSTEM.md §11) ; sous RLS, le worker ne voit personne sans
  cette fonction SECURITY DEFINER, qui ne rend que des identifiants.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_core_preparations"
down_revision: str | Sequence[str] | None = "0017_core_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "core_preparations"
_TS = sa.DateTime(timezone=True)

_USERS = """
CREATE FUNCTION lorakus.core_users_with_module(p_module text)
RETURNS TABLE (user_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
  SELECT m.user_id FROM lorakus.core_user_modules m
  WHERE m.module_id = p_module AND m.enabled
  ORDER BY m.user_id
  LIMIT 1000
$$
"""


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "sections", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("status", sa.Text(), server_default="ready", nullable=False),
        sa.Column("prepared_at", _TS, nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("consulted_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name=f"fk_{_TABLE}_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_TABLE}"),
        sa.UniqueConstraint(
            "user_id", "module", "kind", "day", name="uq_core_preparations_user_id_module_kind_day"
        ),
        sa.CheckConstraint(
            r"module ~ '^[a-z][a-z0-9_]{1,30}$' AND kind ~ '^[a-z][a-z0-9_]{1,30}$'",
            name="names",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120 AND jsonb_typeof(sections) = 'array' "
            "AND jsonb_array_length(sections) <= 8",
            name="content",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'consulted') "
            "AND (status = 'consulted') = (consulted_at IS NOT NULL) "
            "AND expires_at > prepared_at",
            name="status",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_preparations_user_id_expires_at",
        _TABLE,
        ["user_id", "expires_at"],
        schema="lorakus",
    )
    op.execute(f"ALTER TABLE lorakus.{_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE lorakus.{_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_TABLE}_migrator ON lorakus.{_TABLE} TO lorakus_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {_TABLE}_owner_only ON lorakus.{_TABLE} TO lorakus_app "
        "USING (user_id = lorakus.current_user_id()) "
        "WITH CHECK (user_id = lorakus.current_user_id())"
    )
    op.execute(_USERS)
    op.execute("REVOKE ALL ON FUNCTION lorakus.core_users_with_module(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lorakus.core_users_with_module(text) TO lorakus_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION lorakus.core_users_with_module(text)")
    op.drop_table(_TABLE, schema="lorakus")
