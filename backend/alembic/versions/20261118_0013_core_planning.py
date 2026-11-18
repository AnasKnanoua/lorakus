"""core: fuseau du compte, taches et agenda (planning, ADR 0018)

Revision ID: 0013_core_planning
Revises: 0012_core_tool_cancel
Create Date: 2026-11-18

- core_account_settings : fuseau horaire de l'utilisateur (nom IANA). Il etait jusqu'ici
  dans la configuration du module assistant : la valeur deja choisie y est recopiee.
- core_tasks : taches generiques. Sous-taches sur un seul niveau, par une cle composee
  (parent_id, user_id) : une sous-tache appartient forcement au proprietaire du parent.
  Une tache d'un module porte owner_module et owner_ref (unique par module et par objet).
  Statut open ou done ; completed_at present si et seulement si done.
- core_agenda_entries : creneaux concrets, horaires (UTC) ou journees entieres (dates
  locales, fin exclue). Un creneau ecrit par un module porte sa source et son occurrence,
  uniques : une resynchronisation ne cree pas de doublon.
RLS forcee sur les trois tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_core_planning"
down_revision: str | Sequence[str] | None = "0012_core_tool_cancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("core_account_settings", "core_tasks", "core_agenda_entries")
_TS = sa.DateTime(timezone=True)
_MODULE_ID = "owner_module ~ '^[a-z][a-z0-9_]{1,30}$'"


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
        "core_account_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        _now("updated_at"),
        _user_fk("core_account_settings"),
        sa.PrimaryKeyConstraint("user_id", name="pk_core_account_settings"),
        sa.CheckConstraint(
            "timezone ~ '^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$' "
            "AND char_length(timezone) <= 64",
            name="ck_core_account_settings_timezone",
        ),
        schema="lorakus",
    )

    op.create_table(
        "core_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="2", nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("estimate_minutes", sa.Integer(), nullable=True),
        sa.Column("owner_module", sa.Text(), nullable=True),
        sa.Column("owner_ref", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        _now("created_at"),
        _now("updated_at"),
        sa.Column("completed_at", _TS, nullable=True),
        _user_fk("core_tasks"),
        sa.PrimaryKeyConstraint("id", name="pk_core_tasks"),
        sa.UniqueConstraint("id", "user_id", name="uq_core_tasks_id_user_id"),
        sa.ForeignKeyConstraint(
            ["parent_id", "user_id"],
            ["lorakus.core_tasks.id", "lorakus.core_tasks.user_id"],
            name="fk_core_tasks_parent_id_core_tasks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_core_tasks_title"),
        sa.CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 2000", name="ck_core_tasks_notes"
        ),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_core_tasks_status"),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)", name="ck_core_tasks_completed_at"
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 3", name="ck_core_tasks_priority"),
        sa.CheckConstraint(
            "estimate_minutes IS NULL OR estimate_minutes BETWEEN 1 AND 10080",
            name="ck_core_tasks_estimate_minutes",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_core_tasks_parent"),
        sa.CheckConstraint(
            # Ecrite sans resultat NULL possible : une CHECK qui vaut NULL est acceptee.
            "(owner_module IS NULL) = (owner_ref IS NULL) AND (owner_module IS NULL OR "
            f"({_MODULE_ID} AND char_length(owner_ref) BETWEEN 1 AND 200))",
            name="ck_core_tasks_owner",
        ),
        sa.CheckConstraint(
            "source_kind IN ('user', 'conversation', 'module')", name="ck_core_tasks_source_kind"
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_tasks_user_id_status_due_on",
        "core_tasks",
        ["user_id", "status", "due_on"],
        schema="lorakus",
    )
    op.create_index("ix_core_tasks_parent_id", "core_tasks", ["parent_id"], schema="lorakus")
    op.create_index(
        "uq_core_tasks_owner",
        "core_tasks",
        ["user_id", "owner_module", "owner_ref"],
        unique=True,
        schema="lorakus",
        postgresql_where=sa.text("owner_module IS NOT NULL"),
    )

    op.create_table(
        "core_agenda_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("starts_at", _TS, nullable=True),
        sa.Column("ends_at", _TS, nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("owner_module", sa.Text(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("external_key", sa.Text(), nullable=True),
        _now("created_at"),
        _user_fk("core_agenda_entries"),
        sa.PrimaryKeyConstraint("id", name="pk_core_agenda_entries"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_core_agenda_entries_title"
        ),
        sa.CheckConstraint(
            "location IS NULL OR char_length(location) <= 200",
            name="ck_core_agenda_entries_location",
        ),
        # Soit un creneau horaire, soit une journee entiere ; jamais les deux, jamais vide.
        sa.CheckConstraint(
            "(starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at > starts_at "
            "AND start_date IS NULL AND end_date IS NULL) OR "
            "(starts_at IS NULL AND ends_at IS NULL AND start_date IS NOT NULL "
            "AND end_date IS NOT NULL AND end_date > start_date)",
            name="ck_core_agenda_entries_span",
        ),
        sa.CheckConstraint(
            "(owner_module IS NULL) = (source_key IS NULL) "
            "AND (owner_module IS NULL) = (external_key IS NULL) AND (owner_module IS NULL OR "
            f"({_MODULE_ID} AND char_length(source_key) BETWEEN 1 AND 100 "
            "AND char_length(external_key) BETWEEN 1 AND 300))",
            name="ck_core_agenda_entries_source",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_agenda_entries_user_id_starts_at",
        "core_agenda_entries",
        ["user_id", "starts_at"],
        schema="lorakus",
    )
    op.create_index(
        "ix_core_agenda_entries_user_id_start_date",
        "core_agenda_entries",
        ["user_id", "start_date"],
        schema="lorakus",
    )
    op.create_index(
        "uq_core_agenda_entries_source",
        "core_agenda_entries",
        ["user_id", "owner_module", "source_key", "external_key"],
        unique=True,
        schema="lorakus",
        postgresql_where=sa.text("owner_module IS NOT NULL"),
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

    # Le fuseau deja choisi dans la configuration de l'assistant devient celui du compte.
    op.execute(
        "INSERT INTO lorakus.core_account_settings (user_id, timezone) "
        "SELECT user_id, config->>'timezone' FROM lorakus.core_user_modules "
        "WHERE module_id = 'assistant' "
        "AND config->>'timezone' ~ '^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$' "
        "AND char_length(config->>'timezone') <= 64"
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table, schema="lorakus")
