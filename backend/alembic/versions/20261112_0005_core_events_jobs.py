"""core: file de jobs (Procrastinate) et outbox des evenements

Revision ID: 0005_core_events_jobs
Revises: 0004_core_user_modules
Create Date: 2026-11-12

- Schema de Procrastinate 3.10 (tables procrastinate_*), dans le schema lorakus. Seule
  exception a la RLS forcee : files du systeme, sans user_id ; les charges utiles ne
  contiennent que des identifiants, jamais de donnees personnelles (MODULE_SYSTEM.md).
  Une future version de Procrastinate apportera ses fichiers de migration SQL : les
  appliquer par une nouvelle migration Alembic, jamais a la main.
- core_outbox : evenements ecrits dans la meme transaction que le changement qui les cause,
  livres au moins une fois par le worker ; core_outbox_deliveries retient les handlers deja
  passes (un handler n'est pas rejoue apres un redemarrage). L'application ne lit et ne
  modifie la file que par les fonctions outbox_* (SECURITY DEFINER).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_core_events_jobs"
down_revision: str | Sequence[str] | None = "0004_core_user_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_PROCRASTINATE_TABLES = (
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
)

_FUNCTIONS = {
    "outbox_claim(integer,interval)": """
        CREATE FUNCTION lorakus.outbox_claim(p_limit integer, p_lease interval)
        RETURNS TABLE (id bigint, user_id uuid, event_type text, payload jsonb, attempts integer)
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          UPDATE lorakus.core_outbox o SET locked_until = now() + p_lease
          WHERE o.id IN (
            SELECT c.id FROM lorakus.core_outbox c
            WHERE c.published_at IS NULL AND c.dead_at IS NULL
              AND c.next_attempt_at <= now()
              AND (c.locked_until IS NULL OR c.locked_until < now())
            ORDER BY c.id LIMIT p_limit
            FOR UPDATE SKIP LOCKED)
          RETURNING o.id, o.user_id, o.event_type, o.payload, o.attempts
        $$
    """,
    "outbox_done_handlers(bigint)": """
        CREATE FUNCTION lorakus.outbox_done_handlers(p_event bigint) RETURNS SETOF text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$ SELECT handler FROM lorakus.core_outbox_deliveries WHERE event_id = p_event $$
    """,
    "outbox_handler_done(bigint,text)": """
        CREATE FUNCTION lorakus.outbox_handler_done(p_event bigint, p_handler text) RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          INSERT INTO lorakus.core_outbox_deliveries (event_id, handler)
          VALUES (p_event, p_handler) ON CONFLICT DO NOTHING
        $$
    """,
    "outbox_complete(bigint)": """
        CREATE FUNCTION lorakus.outbox_complete(p_event bigint) RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          UPDATE lorakus.core_outbox SET published_at = now(), locked_until = NULL,
            last_error = NULL WHERE id = p_event
        $$
    """,
    "outbox_fail(bigint,text,integer)": """
        CREATE FUNCTION lorakus.outbox_fail(p_event bigint, p_error text, p_max_attempts integer)
        RETURNS void
        LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
          UPDATE lorakus.core_outbox SET
            attempts = attempts + 1,
            last_error = left(p_error, 500),
            locked_until = NULL,
            -- Attente croissante : 2, 4, 8 s... plafonnee a 1 heure.
            next_attempt_at = now() + least(interval '1 hour',
                                            interval '1 second' * power(2, attempts + 1)),
            dead_at = CASE WHEN attempts + 1 >= p_max_attempts THEN now() END
          WHERE id = p_event
        $$
    """,
    "outbox_stats()": """
        CREATE FUNCTION lorakus.outbox_stats()
        RETURNS TABLE (pending bigint, oldest_pending_seconds double precision, dead bigint)
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = lorakus, pg_temp
        AS $$
        BEGIN
          -- Retention : les evenements livres sont gardes 7 jours.
          DELETE FROM lorakus.core_outbox
          WHERE published_at < now() - interval '7 days';
          RETURN QUERY
          SELECT count(*) FILTER (WHERE published_at IS NULL AND dead_at IS NULL),
                 coalesce(extract(epoch FROM now() - min(occurred_at)
                   FILTER (WHERE published_at IS NULL AND dead_at IS NULL)), 0)::double precision,
                 count(*) FILTER (WHERE dead_at IS NOT NULL)
          FROM lorakus.core_outbox;
        END
        $$
    """,
}


def upgrade() -> None:
    # --- Procrastinate : son SQL n'est pas qualifie, il vise le schema courant.
    op.execute("SET LOCAL search_path = lorakus, pg_catalog")
    op.execute(SchemaManager.get_schema())
    op.execute("SET LOCAL search_path = pg_catalog")
    # Pas de RLS sur les tables de Procrastinate, par exception documentee (SECURITY.md) :
    # ce sont des files du systeme, sans colonne user_id ni donnee personnelle, et la RLS
    # y casserait le verrou anti-doublon (PostgreSQL masque alors le detail de l'erreur
    # d'unicite que Procrastinate lit). Les tests verifient qu'aucune table hors de cette
    # liste n'echappe a la RLS forcee.

    # --- Outbox
    op.create_table(
        "core_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("locked_until", _TS, nullable=True),
        sa.Column("published_at", _TS, nullable=True),
        sa.Column("dead_at", _TS, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_core_outbox"),
        schema="lorakus",
    )
    op.create_index(
        "ix_core_outbox_pending",
        "core_outbox",
        ["next_attempt_at"],
        schema="lorakus",
        postgresql_where=sa.text("published_at IS NULL AND dead_at IS NULL"),
    )
    op.create_table(
        "core_outbox_deliveries",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("handler", sa.Text(), nullable=False),
        sa.Column("delivered_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["lorakus.core_outbox.id"],
            name="fk_core_outbox_deliveries_event_id_core_outbox",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "handler", name="pk_core_outbox_deliveries"),
        schema="lorakus",
    )

    for signature, ddl in _FUNCTIONS.items():
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION lorakus.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION lorakus.{signature} TO lorakus_app")

    for table in ("core_outbox", "core_outbox_deliveries"):
        op.execute(f"ALTER TABLE lorakus.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE lorakus.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_migrator ON lorakus.{table} TO lorakus_migrator "
            "USING (true) WITH CHECK (true)"
        )
    # L'application publie (pour l'utilisateur courant, ou un evenement systeme sans
    # utilisateur), lit ses propres evenements, et ne touche au reste que par outbox_*.
    op.execute("REVOKE ALL ON lorakus.core_outbox, lorakus.core_outbox_deliveries FROM lorakus_app")
    op.execute("GRANT SELECT, INSERT ON lorakus.core_outbox TO lorakus_app")
    op.execute(
        "CREATE POLICY core_outbox_publish ON lorakus.core_outbox FOR INSERT TO lorakus_app "
        "WITH CHECK (user_id IS NULL OR user_id = lorakus.current_user_id())"
    )
    op.execute(
        "CREATE POLICY core_outbox_read_own ON lorakus.core_outbox FOR SELECT TO lorakus_app "
        "USING (user_id = lorakus.current_user_id())"
    )


def downgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION lorakus.{signature}")
    op.drop_table("core_outbox_deliveries", schema="lorakus")
    op.drop_table("core_outbox", schema="lorakus")
    for table in reversed(_PROCRASTINATE_TABLES):
        op.execute(f"DROP TABLE IF EXISTS lorakus.{table} CASCADE")
    op.execute(
        "DO $$ DECLARE f record; BEGIN "
        "FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_proc p "
        "WHERE p.pronamespace = 'lorakus'::regnamespace AND p.proname LIKE 'procrastinate%' "
        "LOOP EXECUTE 'DROP FUNCTION ' || f.sig || ' CASCADE'; END LOOP; END $$"
    )
    op.execute(
        "DROP TYPE IF EXISTS lorakus.procrastinate_job_to_defer_v1, "
        "lorakus.procrastinate_job_event_type, lorakus.procrastinate_job_status CASCADE"
    )
