"""core: rang des etapes d'une tache (PR 50)

Revision ID: 0016_core_task_steps
Revises: 0015_core_planning_days
Create Date: 2026-11-21

Le Sergent decoupe une tache en etapes ordonnees (« lire l'enonce », puis « coder », puis
« rediger »). Les etapes sont creees dans la meme transaction : leur date de creation est la
meme, elle ne dit pas leur ordre. `step_number` le garde ; le planificateur place les etapes
d'une tache dans cet ordre. Seule une sous-tache en a un.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_core_task_steps"
down_revision: str | Sequence[str] | None = "0015_core_planning_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "core_tasks", sa.Column("step_number", sa.SmallInteger(), nullable=True), schema="lorakus"
    )
    op.create_check_constraint(
        "step_number",
        "core_tasks",
        "step_number IS NULL OR (parent_id IS NOT NULL AND step_number BETWEEN 1 AND 20)",
        schema="lorakus",
    )


def downgrade() -> None:
    op.drop_constraint("ck_core_tasks_step_number", "core_tasks", schema="lorakus")
    op.drop_column("core_tasks", "step_number", schema="lorakus")
