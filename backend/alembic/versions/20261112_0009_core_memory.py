"""core: memoire de l'utilisateur (faits, refus, reglages)

Revision ID: 0009_core_memory
Revises: 0008_core_rate_limits
Create Date: 2026-11-12

- core_memory_facts : faits sur l'utilisateur. Statut proposed (en attente de sa decision),
  verified (confirme par lui, seul utilise) ou inferred (reserve, sans producteur en v1).
  Provenance (ADR 0015) : source_kind, source_ref, evidence (extrait exact de son message),
  license_constraints. Une seule ligne par texte normalise et par utilisateur.
- core_memory_rejections : empreinte SHA-256 d'un fait refuse, pour ne jamais le reproposer.
  Le texte refuse n'est pas conserve.
- core_memory_settings : reglages par utilisateur (propositions apres les conversations).
RLS forcee sur les trois tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_core_memory"
down_revision: str | Sequence[str] | None = "0008_core_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("core_memory_facts", "core_memory_rejections", "core_memory_settings")
_TS = sa.DateTime(timezone=True)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["lorakus.core_users.id"],
        name=f"fk_{table}_user_id_core_users",
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "core_memory_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("data_class", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "license_constraints",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", _TS, nullable=True),
        _user_fk("core_memory_facts"),
        sa.PrimaryKeyConstraint("id", name="pk_core_memory_facts"),
        sa.UniqueConstraint("user_id", "content_hash", name="uq_core_memory_facts_user_content"),
        sa.CheckConstraint(
            "category IN ('identity', 'preference', 'project', 'habit', 'studies', 'other')",
            name="ck_core_memory_facts_category_known",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'verified', 'inferred')",
            name="ck_core_memory_facts_status_known",
        ),
        sa.CheckConstraint(
            "data_class IN ('personal', 'sensitive')", name="ck_core_memory_facts_data_class_known"
        ),
        sa.CheckConstraint(
            "source_kind IN ('manual', 'conversation')", name="ck_core_memory_facts_source_known"
        ),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 300", name="ck_core_memory_facts_content_length"
        ),
        sa.CheckConstraint(
            "(status = 'verified') = (confirmed_at IS NOT NULL)",
            name="ck_core_memory_facts_confirmed_when_verified",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_memory_facts_user_id_status",
        "core_memory_facts",
        ["user_id", "status"],
        schema="lorakus",
    )
    op.create_table(
        "core_memory_rejections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        _user_fk("core_memory_rejections"),
        sa.PrimaryKeyConstraint("user_id", "content_hash", name="pk_core_memory_rejections"),
        schema="lorakus",
    )
    op.create_table(
        "core_memory_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "propose_after_conversations", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        _user_fk("core_memory_settings"),
        sa.PrimaryKeyConstraint("user_id", name="pk_core_memory_settings"),
        schema="lorakus",
    )
    for table in _TABLES:
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


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table, schema="lorakus")
