"""Export des donnees du module projects (« Mes donnees », PR 41) : idees, projets, taches.

Les taches du planning qui en decoulent sont exportees par le Core avec le reste du planning.
"""

from typing import Any

from sqlalchemy import select

from lorakus.core.data.export import DataExportContext
from lorakus_modules.projects.models import Idea, Project, ProjectTask


async def export_projects(context: DataExportContext) -> dict[str, Any]:
    async with context.open_transaction() as session:
        ideas = list(await session.scalars(select(Idea).order_by(Idea.created_at, Idea.id)))
        projects = list(
            await session.scalars(select(Project).order_by(Project.created_at, Project.id))
        )
        tasks = list(
            await session.scalars(
                select(ProjectTask).order_by(ProjectTask.created_at, ProjectTask.id)
            )
        )
    return {
        "ideas": [
            {
                "id": i.id,
                "text": i.text,
                "status": i.status,
                "source": i.source_ref,
                "created_at": i.created_at,
                "archived_at": i.archived_at,
            }
            for i in ideas
        ],
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "source": p.source_ref,
                "created_at": p.created_at,
                "last_activity_at": p.last_activity_at,
                "finished_at": p.finished_at,
            }
            for p in projects
        ],
        "tasks": [
            {
                "id": t.id,
                "project_id": t.project_id,
                "title": t.title,
                "status": t.status,
                "source": t.source_ref,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in tasks
        ],
    }
