"""core: preferences de planification confirmees

Revision ID: 0014_core_planning_prefs
Revises: 0013_core_planning
Create Date: 2026-11-20

core_planning_preferences : une ligne par utilisateur et par cle d'un catalogue ferme (debut
et fin de la journee de travail, dejeuner, diner, jours sans travail, travail propose par
jour). La valeur est un objet JSON, type par la cle et valide par le code. Une ligne n'existe
que si l'utilisateur a confirme la preference ; sans ligne, la valeur par defaut s'applique.
Classe personal. RLS forcee. Contraintes ecrites pour ne jamais valoir NULL.

Les contraintes CHECK recoivent ici un nom court (« key ») : la convention de nommage ajoute
elle-meme « ck_<table>_ ». Les migrations precedentes donnaient le nom complet, d'ou des noms
doubles en base (ck_core_tasks_ck_core_tasks_title) : sans effet, a ne pas reproduire.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_core_planning_prefs"
down_revision: str | Sequence[str] | None = "0013_core_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "core_planning_preferences"
_KEYS = "'work_start', 'work_end', 'lunch', 'dinner', 'rest_days', 'daily_cap'"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name=f"fk_{_TABLE}_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=f"pk_{_TABLE}"),
        sa.CheckConstraint(f"key IN ({_KEYS})", name="key"),
        sa.CheckConstraint("jsonb_typeof(value) = 'object'", name="value"),
        sa.CheckConstraint(
            "source_kind IN ('user', 'conversation') "
            "AND (source_kind = 'conversation') = (source_ref IS NOT NULL) "
            "AND (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200)",
            name="source",
        ),
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
