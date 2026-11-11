"""core: confirmations d'outils et trace des specialistes

Revision ID: 0006_core_tools_agents
Revises: 0005_core_events_jobs
Create Date: 2026-11-12

- core_tool_confirmations : une action write ou sensitive attend la confirmation de
  l'utilisateur ; usage unique, expiration 10 minutes, liee aux arguments exacts.
- core_agent_runs : trace en ajout seul de chaque appel a un specialiste (ADR 0026).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_core_tools_agents"
down_revision: str | Sequence[str] | None = "0005_core_events_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["lorakus.core_users.id"],
        name=f"fk_{table}_user_id_core_users",
        ondelete="CASCADE",
    )


def _rls(table: str) -> None:
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
    op.create_table(
        "core_tool_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("used_at", _TS, nullable=True),
        _user_fk("core_tool_confirmations"),
        sa.PrimaryKeyConstraint("id", name="pk_core_tool_confirmations"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_tool_confirmations_user_id",
        "core_tool_confirmations",
        ["user_id"],
        schema="lorakus",
    )
    op.create_table(
        "core_agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("specialist", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_eur", sa.Numeric(10, 5), server_default="0", nullable=False),
        sa.Column(
            "data_classes_sent",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        _user_fk("core_agent_runs"),
        sa.PrimaryKeyConstraint("id", name="pk_core_agent_runs"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_agent_runs_user_id_created_at",
        "core_agent_runs",
        ["user_id", "created_at"],
        schema="lorakus",
    )
    for table in ("core_tool_confirmations", "core_agent_runs"):
        _rls(table)
    # Trace en ajout seul : ni modification ni suppression par l'application.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON lorakus.core_agent_runs FROM lorakus_app")
    # Une confirmation ne se supprime pas ; seul used_at est marque.
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON lorakus.core_tool_confirmations FROM lorakus_app"
    )
    op.execute("GRANT UPDATE (used_at) ON lorakus.core_tool_confirmations TO lorakus_app")


def downgrade() -> None:
    op.drop_table("core_agent_runs", schema="lorakus")
    op.drop_table("core_tool_confirmations", schema="lorakus")
