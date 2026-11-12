"""core: journal de consommation des appels IA

Revision ID: 0007_core_ai_usage
Revises: 0006_core_tools_agents
Create Date: 2026-11-12

- core_ai_usage : un appel IA reussi par ligne (tokens, cout en dollars, classe des donnees
  transmises). Sert au plafond mensuel par utilisateur (D-D) et au suivi des couts.
  En ajout seul pour l'application ; RLS forcee comme toute table utilisateur.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_core_ai_usage"
down_revision: str | Sequence[str] | None = "0006_core_tools_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "core_ai_usage"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("data_class", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_core_ai_usage_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_core_ai_usage"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_ai_usage_user_id_created_at",
        _TABLE,
        ["user_id", "created_at"],
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
    # Journal en ajout seul : un cout enregistre ne peut etre ni modifie ni efface par l'API.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON lorakus.{_TABLE} FROM lorakus_app")


def downgrade() -> None:
    op.drop_table(_TABLE, schema="lorakus")
