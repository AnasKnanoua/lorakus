"""core: identite, sessions et isolation par utilisateur (RLS)

Revision ID: 0002_core_identity
Revises: 0001_core_baseline
Create Date: 2026-11-11

Principes (ADR 0008, criteres de la PR 23) :
- chaque table a la RLS activee ET forcee (FORCE : elle s'applique aussi au proprietaire) ;
- lorakus_app ne voit que les lignes de l'utilisateur positionne par set_config(..., true) ;
- lorakus_migrator (proprietaire, migrations et fonctions auth_*) a une politique explicite ;
- avant authentification, l'application ne passe que par des fonctions SECURITY DEFINER
  etroites (auth_*), au search_path fige, dont PUBLIC n'a pas le droit d'execution.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_core_identity"
down_revision: str | Sequence[str] | None = "0001_core_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP = sa.DateTime(timezone=True)

_FUNCTIONS = {
    "current_user_id()": """
        CREATE FUNCTION lorakus.current_user_id() RETURNS uuid
        LANGUAGE sql STABLE SET search_path = lorakus, pg_temp
        AS $$ SELECT nullif(current_setting('lorakus.user_id', true), '')::uuid $$
    """,
    "auth_find_login(text)": """
        CREATE FUNCTION lorakus.auth_find_login(p_email text)
        RETURNS TABLE (id uuid, password_hash text, is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          SELECT u.id, u.password_hash, u.is_active FROM lorakus.core_users u
          WHERE u.email = p_email
        $$
    """,
    "auth_find_session(bytea)": """
        CREATE FUNCTION lorakus.auth_find_session(p_token_hash bytea)
        RETURNS TABLE (id uuid, user_id uuid, last_seen_at timestamptz, expires_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          SELECT s.id, s.user_id, s.last_seen_at, s.expires_at FROM lorakus.core_sessions s
          WHERE s.token_hash = p_token_hash
        $$
    """,
    "auth_failures(text,inet,timestamptz)": """
        CREATE FUNCTION lorakus.auth_failures(p_email text, p_ip inet, p_since timestamptz)
        RETURNS TABLE (by_email bigint, by_ip bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          SELECT
            (SELECT count(*) FROM lorakus.core_login_attempts a
              WHERE a.email = p_email AND a.attempted_at >= p_since),
            (SELECT count(*) FROM lorakus.core_login_attempts a
              WHERE p_ip IS NOT NULL AND a.ip = p_ip AND a.attempted_at >= p_since)
        $$
    """,
    "auth_record_attempt(text,inet,boolean)": """
        CREATE FUNCTION lorakus.auth_record_attempt(p_email text, p_ip inet, p_succeeded boolean)
        RETURNS void
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
        BEGIN
          DELETE FROM lorakus.core_login_attempts WHERE attempted_at < now() - interval '1 day';
          IF p_succeeded THEN
            DELETE FROM lorakus.core_login_attempts WHERE email = p_email;
          ELSE
            INSERT INTO lorakus.core_login_attempts (email, ip) VALUES (p_email, p_ip);
          END IF;
        END
        $$
    """,
    "auth_owner_exists()": """
        CREATE FUNCTION lorakus.auth_owner_exists() RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$ SELECT EXISTS (SELECT 1 FROM lorakus.core_users WHERE role = 'owner') $$
    """,
}


def upgrade() -> None:
    op.create_table(
        "core_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", _TIMESTAMP, server_default=sa.func.now(), nullable=False),
        sa.Column("password_changed_at", _TIMESTAMP, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
        sa.CheckConstraint("role IN ('owner', 'admin', 'user')", name="role_known"),
        sa.PrimaryKeyConstraint("id", name="pk_core_users"),
        sa.UniqueConstraint("email", name="uq_core_users_email"),
        schema="lorakus",
    )
    op.create_table(
        "core_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", _TIMESTAMP, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", _TIMESTAMP, nullable=False),
        sa.Column("expires_at", _TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_core_sessions_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_core_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_core_sessions_token_hash"),
        schema="lorakus",
    )
    op.create_index("ix_core_sessions_user_id", "core_sessions", ["user_id"], schema="lorakus")
    op.create_table(
        "core_login_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("attempted_at", _TIMESTAMP, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_core_login_attempts"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_login_attempts_email_attempted_at",
        "core_login_attempts",
        ["email", "attempted_at"],
        schema="lorakus",
    )
    op.create_index(
        "ix_core_login_attempts_ip_attempted_at",
        "core_login_attempts",
        ["ip", "attempted_at"],
        schema="lorakus",
    )

    for signature, ddl in _FUNCTIONS.items():
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION lorakus.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION lorakus.{signature} TO lorakus_app")

    for table in ("core_users", "core_sessions", "core_login_attempts"):
        op.execute(f"ALTER TABLE lorakus.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lorakus.{table} FORCE ROW LEVEL SECURITY")
        # Le proprietaire (migrations, fonctions auth_*) garde l'acces, explicitement.
        op.execute(
            f"CREATE POLICY {table}_migrator ON lorakus.{table} TO lorakus_migrator "
            "USING (true) WITH CHECK (true)"
        )

    # L'application ne voit que les lignes de l'utilisateur courant.
    op.execute(
        "CREATE POLICY core_users_owner_only ON lorakus.core_users TO lorakus_app "
        "USING (id = lorakus.current_user_id()) WITH CHECK (id = lorakus.current_user_id())"
    )
    op.execute(
        "CREATE POLICY core_sessions_owner_only ON lorakus.core_sessions TO lorakus_app "
        "USING (user_id = lorakus.current_user_id()) "
        "WITH CHECK (user_id = lorakus.current_user_id())"
    )
    # Tentatives de connexion : aucun acces direct pour l'application.
    op.execute("REVOKE ALL ON lorakus.core_login_attempts FROM lorakus_app")
    # Les mots de passe ne changent que par la route dediee ; le role n'est jamais modifiable
    # par l'application (pas d'elevation de privilege par une requete UPDATE).
    op.execute("REVOKE UPDATE ON lorakus.core_users FROM lorakus_app")
    op.execute(
        "GRANT UPDATE (password_hash, password_changed_at) ON lorakus.core_users TO lorakus_app"
    )


def downgrade() -> None:
    for signature in reversed(list(_FUNCTIONS)):
        if signature != "current_user_id()":
            op.execute(f"DROP FUNCTION lorakus.{signature}")
    op.drop_table("core_login_attempts", schema="lorakus")
    op.drop_table("core_sessions", schema="lorakus")
    op.drop_table("core_users", schema="lorakus")
    op.execute("DROP FUNCTION lorakus.current_user_id()")
