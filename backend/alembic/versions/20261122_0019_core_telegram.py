"""core: bot Telegram, liaison des comptes (P5, PR 54)

Revision ID: 0019_core_telegram
Revises: 0018_core_preparations
Create Date: 2026-11-22

- core_telegram_links : discussion privee liee a un utilisateur (une chacun), et le choix de
  recevoir aussi les rappels par Telegram (sans detail). RLS forcee.
- core_telegram_codes : code de liaison en attente, seulement son empreinte SHA-256, valable
  10 minutes, a usage unique. RLS forcee.

Le worker recoit les messages sans savoir de qui ils viennent : deux fonctions SECURITY
DEFINER (comme cal_claim_due), qui ne rendent qu'un identifiant :
- core_telegram_link : consomme un code valide et lie la discussion a son utilisateur ;
- core_telegram_user : l'utilisateur d'une discussion liee.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_core_telegram"
down_revision: str | Sequence[str] | None = "0018_core_preparations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_LINKS = "core_telegram_links"
_CODES = "core_telegram_codes"

_LINK = """
CREATE FUNCTION lorakus.core_telegram_link(p_hash text, p_chat_id bigint, p_now timestamptz)
RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
DECLARE
  v_user uuid;
BEGIN
  DELETE FROM lorakus.core_telegram_codes WHERE expires_at <= p_now;
  DELETE FROM lorakus.core_telegram_codes WHERE code_hash = p_hash RETURNING user_id INTO v_user;
  IF v_user IS NULL THEN
    RETURN NULL;
  END IF;
  -- Une discussion ne sert qu'un compte : liee a un autre, elle change de compte.
  DELETE FROM lorakus.core_telegram_links WHERE chat_id = p_chat_id AND user_id <> v_user;
  INSERT INTO lorakus.core_telegram_links (user_id, chat_id, linked_at)
  VALUES (v_user, p_chat_id, p_now)
  ON CONFLICT (user_id) DO UPDATE
    SET chat_id = EXCLUDED.chat_id, linked_at = EXCLUDED.linked_at, last_message_at = NULL;
  RETURN v_user;
END
$$
"""

_USER = """
CREATE FUNCTION lorakus.core_telegram_user(p_chat_id bigint)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
  SELECT user_id FROM lorakus.core_telegram_links WHERE chat_id = p_chat_id
$$
"""


def _owner_only(table: str) -> None:
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


def _function(sql: str, signature: str) -> None:
    op.execute(sql)
    op.execute(f"REVOKE ALL ON FUNCTION lorakus.{signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION lorakus.{signature} TO lorakus_app")


def upgrade() -> None:
    op.create_table(
        _LINKS,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("notify", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("linked_at", _TS, nullable=False),
        sa.Column("last_message_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name=f"fk_{_LINKS}_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=f"pk_{_LINKS}"),
        sa.UniqueConstraint("chat_id", name=f"uq_{_LINKS}_chat_id"),
        # Discussion privee : son identifiant est celui de l'utilisateur Telegram (> 0).
        sa.CheckConstraint("chat_id > 0", name="private_chat"),
        schema="lorakus",
    )
    _owner_only(_LINKS)
    op.create_table(
        _CODES,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["lorakus.core_users.id"],
            name=f"fk_{_CODES}_user_id_core_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=f"pk_{_CODES}"),
        sa.UniqueConstraint("code_hash", name=f"uq_{_CODES}_code_hash"),
        sa.CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="sha256"),
        schema="lorakus",
    )
    _owner_only(_CODES)
    _function(_LINK, "core_telegram_link(text, bigint, timestamptz)")
    _function(_USER, "core_telegram_user(bigint)")


def downgrade() -> None:
    op.execute("DROP FUNCTION lorakus.core_telegram_user(bigint)")
    op.execute("DROP FUNCTION lorakus.core_telegram_link(text, bigint, timestamptz)")
    op.drop_table(_CODES, schema="lorakus")
    op.drop_table(_LINKS, schema="lorakus")
