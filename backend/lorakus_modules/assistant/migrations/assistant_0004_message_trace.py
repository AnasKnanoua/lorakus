"""assistant: trace de chaque reponse

Revision ID: assistant_0004
Revises: assistant_0003
Create Date: 2026-11-14

asst_messages.trace (PR 39) : ce qui explique une reponse (« Pourquoi m'as-tu dit ca ? ») :
version du prompt, modele, nombre d'appels et cout, souvenirs fournis (par identifiant, jamais
par leur texte), routage et specialistes consultes, classes de donnees transmises au modele.
Supprimee avec la conversation. Colonne facultative : l'ancienne API l'ignore.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "assistant_0004"
down_revision: str | Sequence[str] | None = "assistant_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asst_messages",
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="lorakus",
    )


def downgrade() -> None:
    op.drop_column("asst_messages", "trace", schema="lorakus")
