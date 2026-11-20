"""Planning : /api/v1/planning/... (PR 47, ADR 0018).

`GET /preferences` et `DELETE /preferences/{key}` : les preferences de planification (PR 48),
lues et retirees depuis la page ; les regler passe par une carte du chat.

`GET /today` rend la journee : agenda, plan propose par le planificateur, retards, echeances.
Le plan est une PROPOSITION recalculee a chaque lecture : rien n'est ecrit, ni dans l'agenda
ni ailleurs. La transaction est mise en lecture seule : meme un defaut futur du code ne
pourrait pas ecrire depuis cette route.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from lorakus.api.auth import client_ip, current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.planning.preferences import (
    KEYS,
    LABEL,
    InvalidPreferenceError,
    Key,
    clear_preference,
    current_value,
    load,
    stored,
    value_text,
)
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
    """Un bloc de travail propose. `assumed_duration` : la tache n'a pas de duree estimee."""

    task: TaskOut
    starts_at: datetime
    ends_at: datetime
    minutes: int
    assumed_duration: bool


class LeftoverOut(BaseModel):
    """Ce qui n'a pas trouve de place aujourd'hui."""

    task: TaskOut
    minutes: int


class MealOut(BaseModel):
    """Un repas du jour (preference confirmee) : aucun travail n'y est propose."""

    name: Literal["lunch", "dinner"]
    label: str
    starts_at: datetime
    ends_at: datetime


class PreferenceOut(BaseModel):
    """Une preference de planification, confirmee ou a sa valeur par defaut."""

    key: Key
    label: str
    value: str  # ecrite en francais (« de 12 h 30 à 13 h 30 »)
    is_default: bool


class TodayOut(BaseModel):
    day: date
    timezone: str
    generated_at: datetime
    # Fin de la fenetre de travail du jour ; None : journee de travail finie, ou jour sans
    # travail (`rest_day`).
    work_ends_at: datetime | None
    rest_day: bool
    meals: list[MealOut]
    agenda: list[AgendaEntryOut]
    plan: list[PlanBlockOut]
    planned_minutes: int
    unplanned: list[LeftoverOut]
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


def _out(view: TodayView) -> TodayOut:
    assumed = {str(c.task.id): c.assumed for c in view.plan.candidates}
    return TodayOut(
        day=view.day,
        timezone=view.timezone,
        generated_at=view.now,
        work_ends_at=view.plan.window.end if view.plan.window else None,
        rest_day=view.plan.rest_day,
        meals=[
            MealOut(
                name=cast(Literal["lunch", "dinner"], name),
                label=LABEL[cast(Key, name)],
                starts_at=hours.start,
                ends_at=hours.end,
            )
            for name, hours in view.plan.meals
        ],
        agenda=[_entry(e) for e in view.agenda],
        plan=[
            PlanBlockOut(
                task=_task(view.tasks[str(b.task_id)], view.day),
                starts_at=b.start,
                ends_at=b.end,
                minutes=b.minutes,
                assumed_duration=assumed[str(b.task_id)],
            )
            for b in view.plan.blocks
        ],
        planned_minutes=view.plan.planned_minutes,
        unplanned=[
            LeftoverOut(task=_task(view.tasks[str(left.task_id)], view.day), minutes=left.minutes)
            for left in view.plan.leftovers
        ],
        overdue=[_task(t, view.day) for t in view.overdue],
        upcoming=[_task(t, view.day) for t in view.upcoming],
    )


@router.get("/today")
async def today(user: User, database: Db, now: Now) -> TodayOut:
    async with database.transaction(user.id) as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return _out(await read_today(session, now))


@router.get("/preferences")
async def preferences(user: User, database: Db) -> list[PreferenceOut]:
    """Le catalogue entier, dans son ordre : la valeur confirmee, sinon celle par defaut."""
    async with database.transaction(user.id) as session:
        prefs = await load(session)
        confirmed = {item.key for item in await stored(session)}
    return [
        PreferenceOut(
            key=key,
            label=LABEL[key],
            value=value_text(key, current_value(prefs, key)),
            is_default=key not in confirmed,
        )
        for key in KEYS
    ]


@router.delete("/preferences/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_preference(key: Key, request: Request, user: User, database: Db) -> Response:
    """Retire une preference confirmee : sa valeur par defaut s'applique de nouveau."""
    try:
        async with database.transaction(user.id) as session:
            removed = await clear_preference(session, user.id, key, client_ip(request))
    except InvalidPreferenceError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune préférence enregistrée.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
