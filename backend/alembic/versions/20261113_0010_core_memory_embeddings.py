"""core: vecteurs des faits de la memoire (embeddings locaux)

Revision ID: 0010_core_memory_embeddings
Revises: 0009_core_memory
Create Date: 2026-11-13

- core_memory_embeddings : un vecteur halfvec(384) par fait confirme, calcule localement
  (PR 37, ADR 0007). model_id et content_hash disent pour quel modele et quel texte il a
  ete calcule : un fait corrige ou un modele change le rend perime, il est alors recalcule.
- Cle etrangere composee (fact_id, user_id) vers core_memory_facts : un vecteur appartient
  forcement au proprietaire du fait. Elle s'appuie sur une nouvelle contrainte d'unicite
  (id, user_id) des faits.
- Pas d'index approche (HNSW) : au plus 200 faits par utilisateur, filtres par la RLS ; une
  lecture exacte est plus juste et assez rapide. A revoir avec la recherche dans les
  conversations.
RLS forcee, comme toutes les tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from lorakus.db.vector import HalfVector

revision: str = "0010_core_memory_embeddings"
down_revision: str | Sequence[str] | None = "0009_core_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "core_memory_embeddings"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_core_memory_facts_id_user_id",
        "core_memory_facts",
        ["id", "user_id"],
        schema="lorakus",
    )
    op.create_table(
        _TABLE,
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("embedding", HalfVector(384), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["fact_id", "user_id"],
            ["lorakus.core_memory_facts.id", "lorakus.core_memory_facts.user_id"],
            name="fk_core_memory_embeddings_fact_id_core_memory_facts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_core_memory_embeddings_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fact_id", name="pk_core_memory_embeddings"),
        sa.CheckConstraint(
            "char_length(model_id) BETWEEN 1 AND 100", name="ck_core_memory_embeddings_model_id"
        ),
        schema="lorakus",
    )
    op.create_index("ix_core_memory_embeddings_user_id", _TABLE, ["user_id"], schema="lorakus")
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
    op.drop_constraint(
        "uq_core_memory_facts_id_user_id", "core_memory_facts", type_="unique", schema="lorakus"
    )
