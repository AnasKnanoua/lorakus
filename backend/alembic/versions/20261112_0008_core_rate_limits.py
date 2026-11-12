"""core: compteurs des limites de debit par utilisateur

Revision ID: 0008_core_rate_limits
Revises: 0007_core_ai_usage
Create Date: 2026-11-12

- core_rate_limits : une ligne par utilisateur, compteur et fenetre fixe (PR 35). Les
  fenetres passees d'un compteur sont effacees a l'ouverture de la suivante.
  RLS forcee comme toute table utilisateur.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_core_rate_limits"
down_revision: str | Sequence[str] | None = "0007_core_ai_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "core_rate_limits"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_core_rate_limits_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "bucket", "window_start", name="pk_core_rate_limits"),
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


def downgrade() -> None:
    op.drop_table(_TABLE, schema="lorakus")
