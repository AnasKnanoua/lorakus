"""core: signaux, interventions et abonnements Web Push (P5, ADR 0042)

Revision ID: 0017_core_signals
Revises: 0016_core_task_steps
Create Date: 2026-11-22

- core_signals : une cause d'interruption proposee par un module, une seule fois par
  utilisateur (`dedup_key` unique), avec le texte ecrit par le code, la regle et les faits
  (« Pourquoi ? »), et l'etat de sa carte dans l'application.
- core_interventions : chaque decision d'interrompre, par niveau ; un niveau au plus par
  signal (unique) : jamais deux fois la meme notification.
- core_push_subscriptions : appareils abonnes aux notifications.

Un seul job traite tous les utilisateurs (MODULE_SYSTEM.md §11). Sous RLS, le worker ne voit
rien sans utilisateur courant : deux fonctions SECURITY DEFINER (comme cal_claim_due) ne lui
rendent que des identifiants.
- core_signals_claim_due : signaux a examiner maintenant, reserves pour une duree.
- core_users_with_tasks_due : utilisateurs qui ont le module donne active et, soit une tache
  ouverte a rendre bientot, soit un signal encore vivant de ce module (a retirer peut-etre).

RLS forcee. Contraintes ecrites pour ne jamais valoir NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_core_signals"
down_revision: str | Sequence[str] | None = "0016_core_task_steps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_SIGNALS = "core_signals"
_INTERVENTIONS = "core_interventions"
_PUSH = "core_push_subscriptions"

_CLAIM = """
CREATE FUNCTION lorakus.core_signals_claim_due(
  p_now timestamptz, p_limit integer, p_lease interval)
RETURNS TABLE (id uuid, user_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
  UPDATE lorakus.core_signals s SET locked_until = now() + p_lease
  WHERE s.id IN (
    SELECT c.id FROM lorakus.core_signals c
    WHERE c.status = 'active'
      AND c.next_check_at <= p_now
      AND (c.locked_until IS NULL OR c.locked_until < now())
    ORDER BY c.next_check_at
    LIMIT least(greatest(p_limit, 0), 200)
    FOR UPDATE SKIP LOCKED)
  RETURNING s.id, s.user_id
$$
"""

_DUE_USERS = """
CREATE FUNCTION lorakus.core_users_with_tasks_due(p_until date, p_module text)
RETURNS TABLE (user_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
AS $$
  SELECT u.user_id FROM (
    SELECT t.user_id FROM lorakus.core_tasks t
    WHERE t.status = 'open' AND t.due_on BETWEEN p_until - 10 AND p_until
    UNION
    -- Ceux qui ont encore un signal vivant du module : il faut peut-etre le retirer.
    SELECT s.user_id FROM lorakus.core_signals s
    WHERE s.module = p_module AND s.status IN ('active', 'done')
  ) u
  WHERE EXISTS (
    SELECT 1 FROM lorakus.core_user_modules m
    WHERE m.user_id = u.user_id AND m.module_id = p_module AND m.enabled
  )
  LIMIT 1000
$$
"""


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["lorakus.core_users.id"],
        name=f"fk_{table}_user_id_core_users",
        ondelete="CASCADE",
    )


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
        _SIGNALS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("data_class", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("firm_body", sa.Text(), nullable=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column(
            "facts", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("not_before", _TS, nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("next_check_at", _TS, nullable=True),
        sa.Column("locked_until", _TS, nullable=True),
        sa.Column("seen_at", _TS, nullable=True),
        sa.Column("closed_at", _TS, nullable=True),
        sa.Column("snoozed_until", _TS, nullable=True),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        _user_fk(_SIGNALS),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_SIGNALS}"),
        sa.UniqueConstraint("id", "user_id", name="uq_core_signals_id_user_id"),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_core_signals_user_id_dedup_key"),
        sa.CheckConstraint(
            r"name ~ '^[a-z][a-z0-9_]{1,30}\.[a-z][a-z0-9_]{1,60}$' "
            "AND module = split_part(name, '.', 1)",
            name="name",
        ),
        sa.CheckConstraint("kind IN ('scheduled', 'contextual', 'proactive')", name="kind"),
        sa.CheckConstraint("strength BETWEEN 0 AND 1", name="strength"),
        sa.CheckConstraint("data_class IN ('public', 'personal', 'sensitive')", name="class"),
        sa.CheckConstraint(
            "char_length(dedup_key) BETWEEN 1 AND 200 "
            "AND (subject_ref IS NULL OR char_length(subject_ref) BETWEEN 1 AND 200)",
            name="keys",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120 AND char_length(body) BETWEEN 1 AND 400 "
            "AND (firm_body IS NULL OR char_length(firm_body) BETWEEN 1 AND 400) "
            "AND char_length(rule) BETWEEN 1 AND 300",
            name="texts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(facts) = 'array' AND jsonb_array_length(facts) <= 12", name="facts"
        ),
        sa.CheckConstraint(
            "url ~ '^/[a-z]+(/[a-z0-9_-]+)*$' AND char_length(url) <= 100", name="url"
        ),
        sa.CheckConstraint("expires_at > not_before", name="window"),
        sa.CheckConstraint(
            "status IN ('active', 'done', 'expired', 'withdrawn') "
            "AND (status = 'active') = (next_check_at IS NOT NULL) "
            "AND (outcome IS NULL OR char_length(outcome) BETWEEN 1 AND 40)",
            name="status",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_signals_next_check_at",
        _SIGNALS,
        ["next_check_at"],
        schema="lorakus",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_core_signals_user_id_status", _SIGNALS, ["user_id", "status"], schema="lorakus"
    )
    _owner_only(_SIGNALS)

    op.create_table(
        _INTERVENTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "decision", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("delivered", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("failed", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        _user_fk(_INTERVENTIONS),
        sa.ForeignKeyConstraint(
            ["signal_id", "user_id"],
            ["lorakus.core_signals.id", "lorakus.core_signals.user_id"],
            name="fk_core_interventions_signal_id_core_signals",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_INTERVENTIONS}"),
        sa.UniqueConstraint("signal_id", "level", name="uq_core_interventions_signal_id_level"),
        sa.CheckConstraint(
            "level IN (1, 2) AND channel IN ('app', 'push') AND (level = 1) = (channel = 'app')",
            name="level",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 40 AND jsonb_typeof(decision) = 'object' "
            "AND delivered >= 0 AND failed >= 0",
            name="record",
        ),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_interventions_user_id_created_at",
        _INTERVENTIONS,
        ["user_id", "created_at"],
        schema="lorakus",
    )
    _owner_only(_INTERVENTIONS)

    op.create_table(
        _PUSH,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_success_at", _TS, nullable=True),
        sa.Column("last_failure_at", _TS, nullable=True),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        _user_fk(_PUSH),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_PUSH}"),
        sa.UniqueConstraint(
            "user_id", "endpoint", name="uq_core_push_subscriptions_user_id_endpoint"
        ),
        sa.CheckConstraint(
            "endpoint LIKE 'https://%' AND char_length(endpoint) <= 1024 "
            "AND char_length(p256dh) BETWEEN 80 AND 100 AND char_length(auth) BETWEEN 16 AND 30",
            name="keys",
        ),
        sa.CheckConstraint("char_length(label) BETWEEN 1 AND 60 AND failures >= 0", name="label"),
        schema="lorakus",
    )
    _owner_only(_PUSH)

    _function(_CLAIM, "core_signals_claim_due(timestamptz, integer, interval)")
    _function(_DUE_USERS, "core_users_with_tasks_due(date, text)")


def downgrade() -> None:
    op.execute("DROP FUNCTION lorakus.core_users_with_tasks_due(date, text)")
    op.execute("DROP FUNCTION lorakus.core_signals_claim_due(timestamptz, integer, interval)")
    op.drop_table(_PUSH, schema="lorakus")
    op.drop_table(_INTERVENTIONS, schema="lorakus")
    op.drop_table(_SIGNALS, schema="lorakus")
