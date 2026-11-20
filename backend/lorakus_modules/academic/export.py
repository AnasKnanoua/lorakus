"""Export des donnees du module academic (« Mes donnees », PR 41) : cours et evaluations.

Les taches qui en decoulent sont exportees par le Core avec le reste du planning.
"""

from typing import Any

from sqlalchemy import select

from lorakus.core.data.export import DataExportContext
from lorakus_modules.academic.models import Assessment, Course


async def export_academic(context: DataExportContext) -> dict[str, Any]:
    async with context.open_transaction() as session:
        courses = list(await session.scalars(select(Course).order_by(Course.created_at, Course.id)))
        assessments = list(
            await session.scalars(select(Assessment).order_by(Assessment.created_at, Assessment.id))
        )
    return {
        "courses": [{"id": c.id, "name": c.name, "created_at": c.created_at} for c in courses],
        "assessments": [
            {
                "id": a.id,
                "course_id": a.course_id,
                "kind": a.kind,
                "title": a.title,
                "due_on": a.due_on,
                "weight": a.weight,
                "estimate_minutes": a.estimate_minutes,
                "status": a.status,
                "source": a.source_ref,
                "created_at": a.created_at,
                "completed_at": a.completed_at,
            }
            for a in assessments
        ],
    }
