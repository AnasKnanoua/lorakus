"""Vue « Aujourd'hui » (PR 47 et 49) : le cadre du jour, l'agenda, le plan propose, les
retards, les echeances.

Le jour « en cours » est celui d'hier tant que sa plage de travail n'est pas finie (nuit
blanche) : a 2 h du matin, on est encore dans la journee de la veille.

Une lecture, rien d'autre : la vue est recalculee a chaque demande, a partir de l'agenda, des
taches ouvertes et de l'heure du compte. Elle n'ecrit ni creneau, ni tache, ni trace. La route
qui la sert ouvre d'ailleurs une transaction en lecture seule : PostgreSQL lui-meme refuserait
une ecriture.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import day_bounds
from lorakus.core.account.service import timezone_name, user_timezone
from lorakus.core.planning.days import current_day, get_frame
from lorakus.core.planning.planner import DayPlan, plan_day
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
    # Creneaux qui touchent ce jour ou sa plage de travail, journees entieres d'abord.
    agenda: tuple[AgendaView, ...]
    plan: DayPlan
    tasks: dict[str, TaskView]  # taches ouvertes, par identifiant
    overdue: tuple[TaskView, ...]  # echeance passee, la plus ancienne d'abord
    upcoming: tuple[TaskView, ...]  # echeance d'aujourd'hui a J+7, la plus proche d'abord


def upcoming_tasks(tasks: list[TaskView], today: date) -> tuple[TaskView, ...]:
    last = today + timedelta(days=UPCOMING_DAYS)
    return tuple(t for t in tasks if t.due_on is not None and today <= t.due_on <= last)


def _touches(entry: AgendaView, day: date, start: datetime, end: datetime) -> bool:
    if entry.starts_at is None or entry.ends_at is None:  # journee entiere : ce jour-la
        return entry.start_date is not None and entry.start_date <= day < (entry.end_date or day)
    return entry.starts_at < end and entry.ends_at > start


async def read_today(session: AsyncSession, now: datetime) -> TodayView:
    """La journee de l'utilisateur de la session, vue a l'instant `now` (aware)."""
    tz = await user_timezone(session)
    return await read_day(session, now, await current_day(session, now, tz))


async def read_day(session: AsyncSession, now: datetime, day: date) -> TodayView:
    """La vue d'un jour donne (le lendemain pour le briefing, P5), vue a l'instant `now` :
    meme calcul que « Ma journee », avec le cadre et l'agenda de ce jour-la."""
    tz = await user_timezone(session)
    frame = await get_frame(session, day)
    start, end = day_bounds(day, tz)
    if frame is not None and frame.end is not None:
        end = max(end, frame.end)  # une plage qui passe minuit
    # Deux jours : la plage peut deborder sur le lendemain.
    agenda = [e for e in await agenda_for_days(session, day, 2, tz) if _touches(e, day, start, end)]
    tasks = await list_tasks(session, "open", MAX_LIST)  # par echeance, puis priorite
    return TodayView(
        day=day,
        timezone=await timezone_name(session),
        now=now,
        agenda=tuple(agenda),
        plan=plan_day(now, frame, agenda, tasks),
        tasks={str(t.id): t for t in tasks},
        overdue=tuple(t for t in tasks if t.overdue(day)),
        upcoming=upcoming_tasks(tasks, day),
    )
