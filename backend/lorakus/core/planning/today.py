"""Vue « Aujourd'hui » (PR 47) : l'agenda du jour, le plan propose, les retards, les echeances.

Une lecture, rien d'autre : la vue est recalculee a chaque demande, a partir de l'agenda, des
taches ouvertes et de l'heure du compte. Elle n'ecrit ni creneau, ni tache, ni trace. La route
qui la sert ouvre d'ailleurs une transaction en lecture seule : PostgreSQL lui-meme refuserait
une ecriture.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import local_today
from lorakus.core.account.service import timezone_name, user_timezone
from lorakus.core.planning.planner import DayPlan, plan_day
from lorakus.core.planning.preferences import load
from lorakus.core.planning.service import (
    MAX_LIST,
    AgendaView,
    TaskView,
    agenda_for_days,
    list_tasks,
)

# « Echeances » : aujourd'hui et les sept jours suivants.
UPCOMING_DAYS: Final = 7


@dataclass(frozen=True)
class TodayView:
    day: date
    timezone: str
    now: datetime
    agenda: tuple[AgendaView, ...]  # creneaux qui touchent ce jour, journees entieres d'abord
    plan: DayPlan
    tasks: dict[str, TaskView]  # taches ouvertes, par identifiant
    overdue: tuple[TaskView, ...]  # echeance passee, la plus ancienne d'abord
    upcoming: tuple[TaskView, ...]  # echeance d'aujourd'hui a J+7, la plus proche d'abord


def upcoming_tasks(tasks: list[TaskView], today: date) -> tuple[TaskView, ...]:
    last = today + timedelta(days=UPCOMING_DAYS)
    return tuple(t for t in tasks if t.due_on is not None and today <= t.due_on <= last)


async def read_today(session: AsyncSession, now: datetime) -> TodayView:
    """La journee de l'utilisateur de la session, vue a l'instant `now` (aware)."""
    tz = await user_timezone(session)
    day = local_today(now, tz)
    agenda = await agenda_for_days(session, day, 1, tz)
    tasks = await list_tasks(session, "open", MAX_LIST)  # par echeance, puis priorite
    return TodayView(
        day=day,
        timezone=await timezone_name(session),
        now=now,
        agenda=tuple(agenda),
        plan=plan_day(now, day, tz, agenda, tasks, await load(session)),
        tasks={str(t.id): t for t in tasks},
        overdue=tuple(t for t in tasks if t.overdue(day)),
        upcoming=upcoming_tasks(tasks, day),
    )
