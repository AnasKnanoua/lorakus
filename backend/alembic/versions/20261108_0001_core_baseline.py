"""core: socle initial

Revision ID: 0001_core_baseline
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_core_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("core",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # La table de version d'Alembic ne doit etre modifiable que par les migrations.
    # Les privileges par defaut l'ont rendue modifiable par lorakus_app : on retire ce droit.
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON lorakus.alembic_version FROM lorakus_app"
    )


def downgrade() -> None:
    op.execute("GRANT INSERT, UPDATE, DELETE ON lorakus.alembic_version TO lorakus_app")
