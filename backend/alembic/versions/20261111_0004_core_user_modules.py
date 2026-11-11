"""core: activation et configuration des modules par utilisateur

Revision ID: 0004_core_user_modules
Revises: 0003_core_mfa_keys_audit
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_core_user_modules"
down_revision: str | Sequence[str] | None = "0003_core_mfa_keys_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "core_user_modules",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_core_user_modules_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "module_id", name="pk_core_user_modules"),
        schema="lorakus",
    )
    op.execute("ALTER TABLE lorakus.core_user_modules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lorakus.core_user_modules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY core_user_modules_migrator ON lorakus.core_user_modules "
        "TO lorakus_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY core_user_modules_owner_only ON lorakus.core_user_modules TO lorakus_app "
        "USING (user_id = lorakus.current_user_id()) "
        "WITH CHECK (user_id = lorakus.current_user_id())"
    )


def downgrade() -> None:
    op.drop_table("core_user_modules", schema="lorakus")
