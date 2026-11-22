"""projects : idees venues du bot Telegram (P5, PR 54, scenario 5)

Revision ID: projects_0002
Revises: projects_0001
Create Date: 2026-11-22

Une idee peut maintenant venir de Telegram (`source_kind = 'telegram'`, sans `source_ref`) :
la provenance reste visible, et le texte, donnee externe, passe toujours par inert() avant
d'etre montre au modele.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "projects_0002"
down_revision: str | Sequence[str] | None = "projects_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAIL = (
    "AND (source_kind = 'conversation') = (source_ref IS NOT NULL) "
    "AND (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200)"
)


def _source(kinds: str) -> None:
    op.execute("ALTER TABLE lorakus.proj_ideas DROP CONSTRAINT ck_proj_ideas_source")
    op.execute(
        "ALTER TABLE lorakus.proj_ideas ADD CONSTRAINT ck_proj_ideas_source "
        f"CHECK (source_kind IN ({kinds}) {_TAIL})"
    )


def upgrade() -> None:
    _source("'user', 'conversation', 'telegram'")


def downgrade() -> None:
    # Les idees venues de Telegram deviennent des idees de l'utilisateur (aucune perte).
    op.execute("UPDATE lorakus.proj_ideas SET source_kind = 'user' WHERE source_kind = 'telegram'")
    _source("'user', 'conversation'")
