"""core: double authentification, cles d'API et journal d'audit

Revision ID: 0003_core_mfa_keys_audit
Revises: 0002_core_identity
Create Date: 2026-11-11

- core_totp : secret TOTP chiffre (AES-GCM, cle hors base), dernier pas utilise (anti-rejeu) ;
- core_backup_codes : codes de secours haches, a usage unique ;
- core_api_keys : cles hachees, prefixe visible, portees, expiration, revocation ;
- core_audit_events : journal en ajout seul. lorakus_app n'y ecrit que par la fonction
  audit_record() et n'a ni UPDATE, ni DELETE, ni TRUNCATE (verifie par make db-check) ;
- core_sessions.reauthenticated_at : date de la derniere preuve d'identite (actions sensibles).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_core_mfa_keys_audit"
down_revision: str | Sequence[str] | None = "0002_core_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_USER_FK = ("user_id", "lorakus.core_users.id")

_FUNCTIONS = {
    "auth_find_api_key(text)": """
        CREATE FUNCTION lorakus.auth_find_api_key(p_prefix text)
        RETURNS TABLE (id uuid, user_id uuid, key_hash bytea, scopes text[],
                       expires_at timestamptz, revoked_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          SELECT k.id, k.user_id, k.key_hash, k.scopes, k.expires_at, k.revoked_at
          FROM lorakus.core_api_keys k WHERE k.prefix = p_prefix
        $$
    """,
    "audit_record(uuid,text,text,inet,jsonb)": """
        CREATE FUNCTION lorakus.audit_record(
          p_user_id uuid, p_action text, p_outcome text, p_ip inet, p_details jsonb)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          INSERT INTO lorakus.core_audit_events (user_id, action, outcome, ip, details)
          VALUES (p_user_id, p_action, p_outcome, p_ip, coalesce(p_details, '{}'::jsonb))
        $$
    """,
}


def _user_table(name: str, *columns: sa.Column, pk: str = "id") -> None:  # type: ignore[type-arg]
    op.create_table(
        name,
        *columns,
        sa.ForeignKeyConstraint(
            [_USER_FK[0]],
            [_USER_FK[1]],
            name=f"fk_{name}_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(pk, name=f"pk_{name}"),
        schema="lorakus",
    )


def _protect(table: str, *, owner_column: str = "user_id") -> None:
    op.execute(f"ALTER TABLE lorakus.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE lorakus.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_migrator ON lorakus.{table} TO lorakus_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {table}_owner_only ON lorakus.{table} TO lorakus_app "
        f"USING ({owner_column} = lorakus.current_user_id()) "
        f"WITH CHECK ({owner_column} = lorakus.current_user_id())"
    )


def upgrade() -> None:
    op.add_column(
        "core_sessions", sa.Column("reauthenticated_at", _TS, nullable=True), schema="lorakus"
    )

    _user_table(
        "core_totp",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("confirmed_at", _TS, nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        pk="user_id",
    )
    _user_table(
        "core_backup_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("used_at", _TS, nullable=True),
    )
    op.create_index(
        "ix_core_backup_codes_user_id", "core_backup_codes", ["user_id"], schema="lorakus"
    )
    _user_table(
        "core_api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("last_used_at", _TS, nullable=True),
        sa.Column("revoked_at", _TS, nullable=True),
    )
    op.create_unique_constraint(
        "uq_core_api_keys_prefix", "core_api_keys", ["prefix"], schema="lorakus"
    )
    op.create_index("ix_core_api_keys_user_id", "core_api_keys", ["user_id"], schema="lorakus")

    op.create_table(
        "core_audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        # Pas de cle etrangere : le journal survit a la suppression d'un compte.
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="outcome_known"),
        sa.PrimaryKeyConstraint("id", name="pk_core_audit_events"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_audit_events_user_id_occurred_at",
        "core_audit_events",
        ["user_id", "occurred_at"],
        schema="lorakus",
    )

    for signature, ddl in _FUNCTIONS.items():
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION lorakus.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION lorakus.{signature} TO lorakus_app")

    for table in ("core_totp", "core_backup_codes", "core_api_keys"):
        _protect(table)

    # Journal d'audit : lecture de ses propres evenements seulement, ecriture par
    # audit_record() seulement, jamais de modification ni de suppression.
    op.execute("ALTER TABLE lorakus.core_audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lorakus.core_audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY core_audit_events_migrator ON lorakus.core_audit_events "
        "TO lorakus_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY core_audit_events_read_own ON lorakus.core_audit_events "
        "FOR SELECT TO lorakus_app USING (user_id = lorakus.current_user_id())"
    )
    op.execute("REVOKE ALL ON lorakus.core_audit_events FROM lorakus_app")
    op.execute("GRANT SELECT ON lorakus.core_audit_events TO lorakus_app")


def downgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION lorakus.{signature}")
    op.drop_table("core_audit_events", schema="lorakus")
    op.drop_table("core_api_keys", schema="lorakus")
    op.drop_table("core_backup_codes", schema="lorakus")
    op.drop_table("core_totp", schema="lorakus")
    op.drop_column("core_sessions", "reauthenticated_at", schema="lorakus")
