"""assistant: conversations et messages

Revision ID: assistant_0001
Revises:
Create Date: 2026-11-12

Branche Alembic du module : elle ne depend que du Core (core_users) et d'aucun autre module.
Classe personal : jamais envoyee a un fournisseur gratuit (ADR 0007). RLS forcee.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "assistant_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("assistant",)
depends_on: str | Sequence[str] | None = "0002_core_identity"

_TS = sa.DateTime(timezone=True)


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
        "asst_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_asst_conversations_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asst_conversations"),
        # Cible de la cle etrangere composee des messages (voir plus bas).
        sa.UniqueConstraint("id", "user_id", name="uq_asst_conversations_id_user_id"),
        schema="lorakus",
    )
    op.create_index(
        "ix_asst_conversations_user_id_updated_at",
        "asst_conversations",
        ["user_id", "updated_at"],
        schema="lorakus",
    )
    op.create_table(
        "asst_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_asst_messages_user_id_core_users",
            ondelete="CASCADE",
        ),
        # Cle composee : un message appartient forcement au proprietaire de sa conversation.
        # Les controles de cle etrangere ignorent la RLS ; sans cela, un message pourrait
        # viser la conversation d'un autre utilisateur dont on connaitrait l'identifiant.
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["lorakus.asst_conversations.id", "lorakus.asst_conversations.user_id"],
            name="fk_asst_messages_conversation_id_asst_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asst_messages"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_asst_messages_role"),
        sa.CheckConstraint(
            "status IN ('ok', 'interrupted', 'fallback')", name="ck_asst_messages_status"
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_asst_messages_conversation_id_created_at",
        "asst_messages",
        ["conversation_id", "created_at"],
        schema="lorakus",
    )
    op.create_index("ix_asst_messages_user_id", "asst_messages", ["user_id"], schema="lorakus")
    for table in ("asst_conversations", "asst_messages"):
        _rls(table)


def downgrade() -> None:
    op.drop_table("asst_messages", schema="lorakus")
    op.drop_table("asst_conversations", schema="lorakus")
