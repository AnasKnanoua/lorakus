"""core: annulation et provenance des confirmations d'outils

Revision ID: 0012_core_tool_cancel
Revises: 0011_core_memory_search
Create Date: 2026-11-14

PR 38 (outils dans le chat) :
- cancelled_at : l'utilisateur a refuse l'action depuis sa carte ; elle ne peut plus etre
  confirmee.
- origin : d'ou vient la demande (ex. conversation:<id>), pour la provenance des donnees
  creees et pour retirer les confirmations d'une conversation supprimee.
- Arguments effaces apres decision (confirmee ou annulee) : la ligne ne garde que l'outil et
  l'issue. lorakus_app recoit UPDATE sur cancelled_at et arguments, mais un declencheur
  n'autorise qu'une modification des arguments : les VIDER. L'application ne peut donc
  toujours pas changer les arguments figes d'une action en attente (garantie de la 0006) ;
  les autres colonnes lui restent fermees par les droits par colonne.
Colonnes facultatives ajoutees (expand seul) : l'ancienne version de l'API les ignore.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_core_tool_cancel"
down_revision: str | Sequence[str] | None = "0011_core_memory_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "core_tool_confirmations",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        schema="lorakus",
    )
    op.add_column(
        "core_tool_confirmations",
        sa.Column("origin", sa.Text(), nullable=True),
        schema="lorakus",
    )
    op.create_check_constraint(
        "ck_core_tool_confirmations_one_decision",
        "core_tool_confirmations",
        "used_at IS NULL OR cancelled_at IS NULL",
        schema="lorakus",
    )
    op.execute(
        """
        CREATE FUNCTION lorakus.tool_confirmation_arguments_only_erased() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, lorakus AS $$
        BEGIN
          IF NEW.arguments IS DISTINCT FROM OLD.arguments AND NEW.arguments <> '{}'::jsonb THEN
            RAISE EXCEPTION 'arguments figes : seul leur effacement est permis'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER tool_confirmation_arguments_only_erased "
        "BEFORE UPDATE ON lorakus.core_tool_confirmations FOR EACH ROW "
        "EXECUTE FUNCTION lorakus.tool_confirmation_arguments_only_erased()"
    )
    op.execute(
        "GRANT UPDATE (cancelled_at, arguments) ON lorakus.core_tool_confirmations TO lorakus_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE UPDATE (cancelled_at, arguments) ON lorakus.core_tool_confirmations "
        "FROM lorakus_app"
    )
    op.execute(
        "DROP TRIGGER tool_confirmation_arguments_only_erased ON lorakus.core_tool_confirmations"
    )
    op.execute("DROP FUNCTION lorakus.tool_confirmation_arguments_only_erased()")
    op.drop_constraint(
        "ck_core_tool_confirmations_one_decision",
        "core_tool_confirmations",
        schema="lorakus",
        type_="check",
    )
    op.drop_column("core_tool_confirmations", "origin", schema="lorakus")
    op.drop_column("core_tool_confirmations", "cancelled_at", schema="lorakus")
