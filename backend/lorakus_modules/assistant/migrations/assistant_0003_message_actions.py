"""assistant: outils et cartes de chaque reponse

Revision ID: assistant_0003
Revises: assistant_0002
Create Date: 2026-11-14

asst_messages.actions (PR 38) : indications d'outils et cartes de confirmation montrees avec la
reponse, pour les reafficher au rechargement et les rappeler au modele. Valeur par defaut
'[]' : les messages existants n'ont aucune action, et l'ancienne API ignore la colonne.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "assistant_0003"
down_revision: str | Sequence[str] | None = "assistant_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asst_messages",
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="lorakus",
    )
    op.create_check_constraint(
        "ck_asst_messages_actions_array",
        "asst_messages",
        "jsonb_typeof(actions) = 'array'",
        schema="lorakus",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_asst_messages_actions_array", "asst_messages", schema="lorakus", type_="check"
    )
    op.drop_column("asst_messages", "actions", schema="lorakus")
