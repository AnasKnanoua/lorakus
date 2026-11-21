"""Planning : /api/v1/planning/... (PR 47 et 49, ADR 0018).

`DELETE /days/{day}` : efface le cadre d'un jour (PR 49) depuis la page ; le donner passe
par une carte du chat.

`GET /today` rend la journee : agenda, plan propose par le planificateur, retards, echeances.
Le plan est une PROPOSITION recalculee a chaque lecture : rien n'est ecrit, ni dans l'agenda
ni ailleurs. La transaction est mise en lecture seule : meme un defaut futur du code ne
pourrait pas ecrire depuis cette route.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from lorakus.api.auth import client_ip, current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.planning.days import BREAK_LABEL, BreakKind, DayFrame, clear_frame
from lorakus.core.planning.service import AgendaView, TaskView
from lorakus.core.planning.today import TodayView, read_today
from lorakus.db.database import Database

router = APIRouter(prefix="/v1/planning", tags=["planning"])


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_now() -> datetime:
    """L'instant present ; remplace dans les tests pour fixer « maintenant »."""
    return datetime.now(UTC)


User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[Database, Depends(get_database)]
Now = Annotated[datetime, Depends(get_now)]


class AgendaEntryOut(BaseModel):
    """Un creneau du jour : horaire (instants UTC) ou journee entiere (pas d'heures)."""

    title: str
    location: str | None
    all_day: bool
    starts_at: datetime | None
    ends_at: datetime | None
    module: str | None


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    due_on: date | None
    days_left: int | None  # jours avant l'echeance (0 : aujourd'hui ; negatif : passee)
    overdue: bool
    estimate_minutes: int | None
    priority: int
    module: str | None  # module proprietaire (ex. academic), None : tache personnelle


class PlanBlockOut(BaseModel):
    """Un bloc de travail propose."""

    task: TaskOut
    starts_at: datetime
    ends_at: datetime
    minutes: int


class LeftoverOut(BaseModel):
    """Ce qui n'a pas trouve de place aujourd'hui."""

    task: TaskOut
    minutes: int


class BreakOut(BaseModel):
    """Une pause du cadre (repas, sport...) : aucun travail n'y est propose."""

    kind: BreakKind
    label: str
    starts_at: datetime
    ends_at: datetime


class FrameOut(BaseModel):
    """Le cadre du jour donne par l'utilisateur. `off` : pas de travail ce jour-la ; sinon la
    plage de travail (elle peut finir le lendemain) et ses pauses."""

    off: bool
    starts_at: datetime | None
    ends_at: datetime | None
    breaks: list[BreakOut]


class TodayOut(BaseModel):
    day: date
    timezone: str
    generated_at: datetime
    # None : l'utilisateur n'a pas dit quand il travaille ce jour-la ; aucun creneau propose.
    frame: FrameOut | None
    agenda: list[AgendaEntryOut]
    plan: list[PlanBlockOut]
    planned_minutes: int
    unplanned: list[LeftoverOut]
    # Taches sans duree : jamais placees, Lorakus demande combien de temps elles prendront.
    unestimated: list[TaskOut]
    overdue: list[TaskOut]
    upcoming: list[TaskOut]


def _task(task: TaskView, today: date) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        due_on=task.due_on,
        days_left=None if task.due_on is None else (task.due_on - today).days,
        overdue=task.overdue(today),
        estimate_minutes=task.estimate_minutes,
        priority=task.priority,
        module=task.owner_module,
    )


def _entry(entry: AgendaView) -> AgendaEntryOut:
    return AgendaEntryOut(
        title=entry.title,
        location=entry.location,
        all_day=entry.all_day,
        starts_at=entry.starts_at,
        ends_at=entry.ends_at,
        module=entry.owner_module,
    )


def _frame(frame: DayFrame | None) -> FrameOut | None:
    if frame is None:
        return None
    return FrameOut(
        off=frame.off,
        starts_at=frame.start,
        ends_at=frame.end,
        breaks=[
            BreakOut(kind=p.kind, label=BREAK_LABEL[p.kind], starts_at=p.start, ends_at=p.end)
            for p in frame.breaks
        ],
    )


def _out(view: TodayView) -> TodayOut:
    return TodayOut(
        day=view.day,
        timezone=view.timezone,
        generated_at=view.now,
        frame=_frame(view.plan.frame),
        agenda=[_entry(e) for e in view.agenda],
        plan=[
            PlanBlockOut(
                task=_task(view.tasks[str(b.task_id)], view.day),
                starts_at=b.start,
                ends_at=b.end,
                minutes=b.minutes,
            )
            for b in view.plan.blocks
        ],
        planned_minutes=view.plan.planned_minutes,
        unplanned=[
            LeftoverOut(task=_task(view.tasks[str(left.task_id)], view.day), minutes=left.minutes)
            for left in view.plan.leftovers
        ],
        unestimated=[_task(c.task, view.day) for c in view.plan.unestimated],
        overdue=[_task(t, view.day) for t in view.overdue],
        upcoming=[_task(t, view.day) for t in view.upcoming],
    )


@router.get("/today")
async def today(user: User, database: Db, now: Now) -> TodayOut:
    async with database.transaction(user.id) as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return _out(await read_today(session, now))


@router.delete("/days/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_day(day: date, request: Request, user: User, database: Db) -> Response:
    """Efface le cadre d'un jour : plus aucun creneau propose ce jour-la."""
    async with database.transaction(user.id) as session:
        removed = await clear_frame(session, user.id, day, client_ip(request))
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun cadre pour ce jour.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
