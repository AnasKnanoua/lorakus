"""calendars: abonnements ICS

Revision ID: calendars_0001
Revises:
Create Date: 2026-11-18

Branche Alembic du module : elle ne depend que du Core (core_users, core_user_modules).
Classe personal. RLS forcee.

Un seul job synchronise tous les utilisateurs (MODULE_SYSTEM.md §11). Sous RLS, le worker ne
voit les abonnements de personne sans utilisateur courant : la fonction cal_claim_due
(SECURITY DEFINER, comme outbox_claim) lui rend seulement des identifiants (abonnement,
utilisateur) dus, et les reserve pour une duree ; le reste se lit ensuite sous la RLS de
chaque utilisateur. Rien d'autre n'est expose.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "calendars_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("calendars",)
depends_on: str | Sequence[str] | None = "0004_core_user_modules"

_TS = sa.DateTime(timezone=True)
# Contraintes ecrites pour ne jamais valoir NULL (une CHECK a NULL est acceptee).
ERROR_CODES = (
    "invalid_url",
    "forbidden_address",
    "dns",
    "connect",
    "tls",
    "timeout",
    "too_large",
    "too_many_redirects",
    "http_status",
    "encoding",
    "protocol",
    "not_calendar",
    "unreadable",
    "too_many_events",
    "too_slow",
    "rejected_entries",
    "secret_unreadable",
)

_CLAIM = """
CREATE FUNCTION lorakus.cal_claim_due(p_limit integer, p_lease interval)
RETURNS TABLE (id uuid, user_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
  UPDATE lorakus.cal_subscriptions s SET locked_until = now() + p_lease
  WHERE s.id IN (
    SELECT c.id FROM lorakus.cal_subscriptions c
    WHERE c.next_sync_at <= now()
      AND (c.locked_until IS NULL OR c.locked_until < now())
      -- Module desactive : ni routes, ni outils, ni jobs pour cet utilisateur.
      AND EXISTS (
        SELECT 1 FROM lorakus.core_user_modules m
        WHERE m.user_id = c.user_id AND m.module_id = 'calendars' AND m.enabled
      )
    ORDER BY c.next_sync_at
    LIMIT least(greatest(p_limit, 0), 100)
    FOR UPDATE SKIP LOCKED)
  RETURNING s.id, s.user_id
$$
"""


def upgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in ERROR_CODES)
    op.create_table(
        "cal_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url_ciphertext", sa.Text(), nullable=False),
        sa.Column("url_digest", sa.LargeBinary(), nullable=False),
        sa.Column("url_hint", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_status", sa.SmallInteger(), nullable=True),
        sa.Column("entries_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", _TS, nullable=True),
        sa.Column("last_success_at", _TS, nullable=True),
        sa.Column("next_sync_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("locked_until", _TS, nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name="fk_cal_subscriptions_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cal_subscriptions"),
        sa.UniqueConstraint(
            "user_id", "url_digest", name="uq_cal_subscriptions_user_id_url_digest"
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
        sa.CheckConstraint("char_length(url_hint) BETWEEN 1 AND 260", name="hint_length"),
        sa.CheckConstraint("octet_length(url_digest) = 32", name="digest_length"),
        sa.CheckConstraint("url_ciphertext LIKE 'v1:%'", name="url_encrypted"),
        sa.CheckConstraint("status IN ('pending', 'ok', 'error')", name="status_known"),
        # Une erreur a toujours un code connu, et seulement en erreur.
        sa.CheckConstraint(
            f"(status = 'error') = (error_code IS NOT NULL) "
            f"AND coalesce(error_code IN ({codes}), true)",
            name="error_coherent",
        ),
        sa.CheckConstraint(
            "coalesce(error_status BETWEEN 100 AND 599, true) "
            "AND (error_status IS NULL OR coalesce(error_code = 'http_status', false))",
            name="error_status_coherent",
        ),
        sa.CheckConstraint(
            "entries_count >= 0 AND skipped_count >= 0 AND failures >= 0", name="counts"
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_cal_subscriptions_user_id", "cal_subscriptions", ["user_id"], schema="lorakus"
    )
    op.create_index(
        "ix_cal_subscriptions_next_sync_at",
        "cal_subscriptions",
        ["next_sync_at"],
        schema="lorakus",
    )
    op.execute("ALTER TABLE lorakus.cal_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lorakus.cal_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cal_subscriptions_migrator ON lorakus.cal_subscriptions "
        "TO lorakus_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY cal_subscriptions_owner_only ON lorakus.cal_subscriptions "
        "TO lorakus_app USING (user_id = lorakus.current_user_id()) "
        "WITH CHECK (user_id = lorakus.current_user_id())"
    )
    op.execute(_CLAIM)
    op.execute("REVOKE ALL ON FUNCTION lorakus.cal_claim_due(integer, interval) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION lorakus.cal_claim_due(integer, interval) TO lorakus_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION lorakus.cal_claim_due(integer, interval)")
    op.drop_table("cal_subscriptions", schema="lorakus")
