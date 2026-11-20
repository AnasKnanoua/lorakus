"""academic: cours et evaluations

Revision ID: academic_0001
Revises:
Create Date: 2026-11-20

Branche Alembic du module : elle ne depend que du Core (core_users, et le planning dont le
module utilise les taches). Classe personal. RLS forcee.

- acad_courses : un cours par nom (name_key : sans casse ni accents).
- acad_assessments : devoir ou examen d'un cours, par une cle composee (course_id, user_id) :
  une evaluation appartient forcement au proprietaire du cours. Echeance obligatoire (un jour
  local). Statut open ou done ; completed_at present si et seulement si done.
Contraintes ecrites pour ne jamais valoir NULL (une CHECK a NULL est acceptee).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "academic_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("academic",)
depends_on: str | Sequence[str] | None = "0013_core_planning"

_TABLES = ("acad_courses", "acad_assessments")
_TS = sa.DateTime(timezone=True)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["lorakus.core_users.id"],
        name=f"fk_{table}_user_id_core_users",
        ondelete="CASCADE",
    )


def _now(name: str) -> sa.Column[object]:
    return sa.Column(name, _TS, server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "acad_courses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        _now("created_at"),
        _user_fk("acad_courses"),
        sa.PrimaryKeyConstraint("id", name="pk_acad_courses"),
        sa.UniqueConstraint("id", "user_id", name="uq_acad_courses_id_user_id"),
        sa.UniqueConstraint("user_id", "name_key", name="uq_acad_courses_user_id_name_key"),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ck_acad_courses_name"),
        sa.CheckConstraint(
            "char_length(name_key) BETWEEN 1 AND 200", name="ck_acad_courses_name_key"
        ),
        schema="lorakus",
    )

    op.create_table(
        "acad_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("weight", sa.Numeric(5, 2), nullable=True),
        sa.Column("estimate_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("completed_at", _TS, nullable=True),
        _user_fk("acad_assessments"),
        sa.PrimaryKeyConstraint("id", name="pk_acad_assessments"),
        sa.ForeignKeyConstraint(
            ["course_id", "user_id"],
            ["lorakus.acad_courses.id", "lorakus.acad_courses.user_id"],
            name="fk_acad_assessments_course_id_acad_courses",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('assignment', 'exam')", name="ck_acad_assessments_kind"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 110", name="ck_acad_assessments_title"
        ),
        sa.CheckConstraint(
            "weight IS NULL OR (weight > 0 AND weight <= 100)", name="ck_acad_assessments_weight"
        ),
        sa.CheckConstraint(
            "estimate_minutes IS NULL OR estimate_minutes BETWEEN 1 AND 10080",
            name="ck_acad_assessments_estimate_minutes",
        ),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_acad_assessments_status"),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)",
            name="ck_acad_assessments_completed_at",
        ),
        # Une evaluation venue du chat garde sa conversation ; saisie dans la page, rien.
        sa.CheckConstraint(
            "source_kind IN ('user', 'conversation') "
            "AND (source_kind = 'conversation') = (source_ref IS NOT NULL) "
            "AND (source_ref IS NULL OR char_length(source_ref) BETWEEN 1 AND 200)",
            name="ck_acad_assessments_source",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_acad_assessments_user_id_status_due_on",
        "acad_assessments",
        ["user_id", "status", "due_on"],
        schema="lorakus",
    )
    op.create_index(
        "ix_acad_assessments_course_id", "acad_assessments", ["course_id"], schema="lorakus"
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
