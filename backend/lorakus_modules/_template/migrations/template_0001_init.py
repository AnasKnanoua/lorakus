"""template: tables initiales

Revision ID: template_0001
Revises:
Create Date: 2026-11-11

Branche Alembic du module : elle ne depend que du Core (core_users) et d'aucun autre module.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "template_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("template",)
depends_on: str | Sequence[str] | None = "0002_core_identity"


def upgrade() -> None:
    op.create_table(
        "tpl_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_tpl_items_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tpl_items"),
        schema="lorakus",
    )
    op.create_index("ix_tpl_items_user_id", "tpl_items", ["user_id"], schema="lorakus")
    # Isolation par utilisateur : RLS activee ET forcee, politique par role (ADR 0008).
    op.execute("ALTER TABLE lorakus.tpl_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lorakus.tpl_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tpl_items_migrator ON lorakus.tpl_items TO lorakus_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY tpl_items_owner_only ON lorakus.tpl_items TO lorakus_app "
        "USING (user_id = lorakus.current_user_id()) "
        "WITH CHECK (user_id = lorakus.current_user_id())"
    )


def downgrade() -> None:
    op.drop_table("tpl_items", schema="lorakus")
