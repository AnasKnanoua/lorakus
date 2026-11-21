"""Routes du module projects, montees sous /api/v1/projects (PR 51).

Le Core ajoute la verification de session et d'activation du module. « Aujourd'hui », les
retards et les jours sans activite sont calcules ICI, dans le fuseau du compte, avec
l'horloge `get_now` (remplacable en test).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from lorakus.api.auth import client_ip, current_user
from lorakus.core.account.clock import local_today
from lorakus.core.account.service import user_timezone
from lorakus.core.identity.service import CurrentUser
from lorakus.core.planning.service import MAX_ESTIMATE_MINUTES
from lorakus.db.database import Database
from lorakus_modules.projects.service import (
    MAX_DESCRIPTION_CHARS,
    MAX_IDEA_CHARS,
    MAX_NAME_CHARS,
    MAX_TASK_CHARS,
    IdeaNotFoundError,
    IdeaView,
    ProjectNotFoundError,
    ProjectsError,
    ProjectTaskNotFoundError,
    ProjectView,
    TaskLine,
    add_idea,
    add_project,
    add_project_task,
    archive_idea,
    check_due,
    complete_project_task,
    delete_idea,
    delete_project,
    delete_project_task,
    finish_project,
    list_ideas,
    list_projects,
)

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]
IDEA_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Idée introuvable.")
PROJECT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
TASK_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")


def get_now() -> datetime:
    """L'instant de la requete (remplacable en test)."""
    return datetime.now(UTC)


Now = Annotated[datetime, Depends(get_now)]


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _refused(error: ProjectsError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


# --------------------------------------------------------------- schemas
class IdeaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_IDEA_CHARS)


class IdeaOut(BaseModel):
    id: uuid.UUID
    text: str
    status: Literal["inbox", "archived"]
    created_at: datetime


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    # Depuis une idee de la boite : elle disparait, son texte devient la description.
    idea_id: uuid.UUID | None = None


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TASK_CHARS)
    due_on: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=1, le=MAX_ESTIMATE_MINUTES)


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_minutes: int | None = Field(default=None, ge=1, le=MAX_ESTIMATE_MINUTES)


class ProjectTaskOut(BaseModel):
    id: uuid.UUID
    title: str
    status: Literal["open", "done"]
    due_on: date | None
    overdue: bool
    estimate_minutes: int | None
    completed_at: datetime | None


class ProjectOut(BaseModel):
    """Un projet. `idle_days` : jours sans activite d'un projet actif qui dort (14 ou plus)."""

    id: uuid.UUID
    name: str
    description: str | None
    status: Literal["active", "done"]
    open_tasks: int
    done_tasks: int
    idle_days: int | None
    last_activity_at: datetime
    finished_at: datetime | None
    tasks: list[ProjectTaskOut]


def _idea(view: IdeaView) -> IdeaOut:
    return IdeaOut(
        id=view.id,
        text=view.text,
        status=cast(Literal["inbox", "archived"], view.status),
        created_at=view.created_at,
    )


def _task(line: TaskLine, today: date) -> ProjectTaskOut:
    return ProjectTaskOut(
        id=line.id,
        title=line.title,
        status=cast(Literal["open", "done"], line.status),
        due_on=line.due_on,
        overdue=line.status == "open" and line.due_on is not None and line.due_on < today,
        estimate_minutes=line.estimate_minutes,
        completed_at=line.completed_at,
    )


def _project(view: ProjectView, now: datetime, today: date) -> ProjectOut:
    return ProjectOut(
        id=view.id,
        name=view.name,
        description=view.description,
        status=cast(Literal["active", "done"], view.status),
        open_tasks=view.open_tasks,
        done_tasks=view.done_tasks,
        idle_days=view.idle_days(now),
        last_activity_at=view.last_activity_at,
        finished_at=view.finished_at,
        tasks=[_task(t, today) for t in view.tasks],
    )


# ------------------------------------------------------------------ idees
@router.get("/ideas")
async def get_ideas(
    request: Request, user: User, state: Literal["inbox", "archived"] = "inbox"
) -> list[IdeaOut]:
    async with _database(request).transaction(user.id) as session:
        return [_idea(i) for i in await list_ideas(session, state)]


@router.post("/ideas", status_code=status.HTTP_201_CREATED)
async def create_idea(body: IdeaIn, request: Request, user: User) -> IdeaOut:
    try:
        async with _database(request).transaction(user.id) as session:
            return _idea(await add_idea(session, user.id, body.text, ip=client_ip(request)))
    except ProjectsError as error:
        raise _refused(error) from None


@router.post("/ideas/{idea_id}/archive")
async def archive(idea_id: uuid.UUID, request: Request, user: User, now: Now) -> IdeaOut:
    try:
        async with _database(request).transaction(user.id) as session:
            return _idea(await archive_idea(session, user.id, idea_id, now, client_ip(request)))
    except ProjectsError as error:
        raise _refused(error) from None
    except IdeaNotFoundError:
        raise IDEA_NOT_FOUND from None


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_idea(idea_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            await delete_idea(session, user.id, idea_id, client_ip(request))
    except IdeaNotFoundError:
        raise IDEA_NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- projets
@router.get("/projects")
async def get_projects(
    request: Request, user: User, now: Now, state: Literal["active", "done"] = "active"
) -> list[ProjectOut]:
    async with _database(request).transaction(user.id) as session:
        today = local_today(now, await user_timezone(session))
        return [_project(p, now, today) for p in await list_projects(session, state)]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, request: Request, user: User, now: Now) -> ProjectOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(now, await user_timezone(session))
            view = await add_project(
                session,
                user.id,
                body.name,
                body.description,
                idea_id=body.idea_id,
                now=now,
                ip=client_ip(request),
            )
            return _project(view, now, today)
    except ProjectsError as error:
        raise _refused(error) from None
    except IdeaNotFoundError:
        raise IDEA_NOT_FOUND from None


@router.post("/projects/{project_id}/finish")
async def finish(project_id: uuid.UUID, request: Request, user: User, now: Now) -> ProjectOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(now, await user_timezone(session))
            view = await finish_project(session, user.id, project_id, now, client_ip(request))
            return _project(view, now, today)
    except ProjectsError as error:
        raise _refused(error) from None
    except ProjectNotFoundError:
        raise PROJECT_NOT_FOUND from None


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project(project_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            await delete_project(session, user.id, project_id, client_ip(request))
    except ProjectNotFoundError:
        raise PROJECT_NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------- taches de projet
@router.post("/projects/{project_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID, body: TaskIn, request: Request, user: User, now: Now
) -> ProjectOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(now, await user_timezone(session))
            if body.due_on is not None:
                check_due(body.due_on, today, allow_past=True)
            view = await add_project_task(
                session,
                user.id,
                project_id,
                body.title,
                due_on=body.due_on,
                estimate_minutes=body.estimate_minutes,
                now=now,
                ip=client_ip(request),
            )
            return _project(view, now, today)
    except ProjectsError as error:
        raise _refused(error) from None
    except ProjectNotFoundError:
        raise PROJECT_NOT_FOUND from None


@router.post("/tasks/{task_id}/complete")
async def finish_task(
    task_id: uuid.UUID, request: Request, user: User, now: Now, body: CompleteIn | None = None
) -> ProjectOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(now, await user_timezone(session))
            view = await complete_project_task(
                session,
                user.id,
                task_id,
                now,
                client_ip(request),
                actual_minutes=None if body is None else body.actual_minutes,
            )
            return _project(view, now, today)
    except ProjectsError as error:
        raise _refused(error) from None
    except ProjectTaskNotFoundError:
        raise TASK_NOT_FOUND from None


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_task(task_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            await delete_project_task(session, user.id, task_id, client_ip(request))
    except ProjectTaskNotFoundError:
        raise TASK_NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
