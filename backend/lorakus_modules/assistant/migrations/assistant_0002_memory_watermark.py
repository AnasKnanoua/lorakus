"""assistant: point de reprise de la memoire par conversation

Revision ID: assistant_0002
Revises: assistant_0001
Create Date: 2026-11-12

asst_conversations.memory_scanned_until : date du dernier message de l'utilisateur deja
analyse pour proposer des faits (PR 36). Les messages suivants seront analyses a leur tour.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "assistant_0002"
down_revision: str | Sequence[str] | None = "assistant_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asst_conversations",
        sa.Column("memory_scanned_until", sa.DateTime(timezone=True), nullable=True),
        schema="lorakus",
    )


def downgrade() -> None:
    op.drop_column("asst_conversations", "memory_scanned_until", schema="lorakus")
