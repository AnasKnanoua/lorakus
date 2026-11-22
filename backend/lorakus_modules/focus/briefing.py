"""Briefing du lendemain (P5, ADR 0028 et 0042, scenario 3) : le Sergent prepare la journee.

Quand :
- des que ta plage de travail du jour est finie, le briefing du LENDEMAIN est prepare ;
- sinon (aucune plage donnee, jour sans travail), celui du jour en cours est prepare a minuit.
Aucune heure supposee : c'est ta journee, telle que tu l'as dite, qui decide.

Le briefing est refait a chaque passage (toutes les 15 minutes) tant que tu ne l'as pas lu :
il suit ton agenda et tes taches. Une fois lu, il est fige et disparait. Un seul par jour.
Il ne sonne pas : il t'attend en tete de « Ma journee » (decision du 2026-11-22, ADR 0042) ;
une notification chaque matin userait le budget de 3 par jour.

Contenu, par des regles (aucun modele de langage, aucun cout) : l'agenda du jour, ta journee
(plage, plan propose, taches sans duree), les echeances des 3 jours, les retards.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import day_bounds
from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.jobs.port import JobContext, periodic
from lorakus.core.planning.days import current_day, get_frame
from lorakus.core.planning.service import TaskView
from lorakus.core.planning.today import TodayView, read_day
from lorakus.core.preparations.service import Section, prepare
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.focus")

KIND: Final = "briefing"
SOON_DAYS: Final = 3
SHOWN: Final = 6  # lignes par liste, la suite est comptee


def _short(text_: str, limit: int = 90) -> str:
    return text_ if len(text_) <= limit else text_[: limit - 1] + "…"


def _clock(moment: datetime, tz: ZoneInfo) -> str:
    return f"{moment.astimezone(tz):%H:%M}"


def _capped(lines: list[str], what: str) -> list[str]:
    if len(lines) <= SHOWN:
        return lines
    rest = len(lines) - (SHOWN - 1)
    return [*lines[: SHOWN - 1], f"… et {rest} autres {what}."]


def _agenda(view: TodayView, tz: ZoneInfo) -> Section:
    lines: list[str] = []
    for entry in view.agenda:
        where = f" · {_short(entry.location, 40)}" if entry.location else ""
        if entry.starts_at is None or entry.ends_at is None:
            lines.append(f"Toute la journée · {_short(entry.title)}{where}")
        else:
            span = f"{_clock(entry.starts_at, tz)} - {_clock(entry.ends_at, tz)}"
            lines.append(f"{span} · {_short(entry.title)}{where}")
    return Section("Agenda", _capped(lines, "créneaux") or ["Rien à l'agenda."])


def _day(view: TodayView, tz: ZoneInfo) -> Section:
    plan, frame = view.plan, view.plan.frame
    if frame is None:
        return Section(
            "Ta journée",
            [
                "Pas encore décrite : dis-moi dans le chat quand tu travailles, "
                "et je placerai tes tâches."
            ],
        )
    if frame.off or frame.start is None or frame.end is None:
        return Section("Ta journée", ["Jour sans travail : rien n'est proposé."])
    head = f"Travail de {_clock(frame.start, tz)} à {_clock(frame.end, tz)}"
    if frame.breaks:
        head += ", pauses " + ", ".join(
            f"{_clock(p.start, tz)} - {_clock(p.end, tz)}" for p in frame.breaks
        )
    lines = [head + "."]
    if plan.blocks:
        lines.append(f"Proposé : {duration(plan.planned_minutes)} de travail.")
        blocks = [
            f"{_clock(b.start, tz)} - {_clock(b.end, tz)} · "
            f"{_short(view.tasks[str(b.task_id)].title)}"
            for b in plan.blocks
        ]
        lines.extend(blocks[:4])
        rest = len(blocks) - 4
        if rest == 1:
            lines.append("… et 1 autre créneau proposé.")
        elif rest > 1:
            lines.append(f"… et {rest} autres créneaux proposés.")
    elif plan.window is not None:
        lines.append("Rien à placer dans ta plage de travail.")
    count = len(plan.unestimated)
    if count == 1:
        lines.append("1 tâche sans durée : dis-moi combien de temps elle prendra.")
    elif count > 1:
        lines.append(f"{count} tâches sans durée : dis-moi combien de temps elles prendront.")
    return Section("Ta journée", lines)


def _due_line(task: TaskView, due: date, day: date) -> str:
    return f"{_short(task.title)} · {french_date(due)} ({relative_day(due, day)})"


def _deadlines(view: TodayView) -> Section:
    last = view.day + timedelta(days=SOON_DAYS)
    lines = [
        _due_line(t, t.due_on, view.day)
        for t in view.upcoming
        if t.parent_id is None and t.due_on is not None and t.due_on <= last
    ]
    return Section(
        "Échéances", _capped(lines, "échéances") or ["Aucune échéance dans les 3 jours."]
    )


def _late(view: TodayView) -> Section | None:
    """En retard CE jour-la : une tache due la veille et pas faite le sera au reveil."""
    late = sorted(
        (t.due_on, t.title, str(t.id), t)
        for t in view.tasks.values()
        if t.parent_id is None and t.due_on is not None and t.due_on < view.day
    )
    if not late:
        return None
    lines = [_due_line(task, due, view.day) for due, _, _, task in late]
    return Section("En retard", _capped(lines, "tâches en retard"))


def sections(view: TodayView) -> list[Section]:
    """Le briefing du jour `view.day`, ecrit du point de vue de ce jour-la."""
    tz = ZoneInfo(view.timezone)
    parts = [_agenda(view, tz), _day(view, tz), _deadlines(view)]
    late = _late(view)
    if late is not None:
        parts.append(late)
    return parts


def title(day: date) -> str:
    text_ = french_date(day)
    return text_[:1].upper() + text_[1:]


async def target_day(session: AsyncSession, now: datetime) -> date:
    """Le jour a preparer : le lendemain si la plage du jour est finie, sinon le jour en
    cours (prepare des minuit). Un jour sans travail n'a pas de fin de plage."""
    tz = await user_timezone(session)
    today = await current_day(session, now, tz)
    frame = await get_frame(session, today)
    if frame is not None and frame.end is not None and now >= frame.end:
        return today + timedelta(days=1)
    return today


async def prepare_briefing(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> bool:
    """Prepare (ou rafraichit) le briefing qui convient maintenant ; False s'il a deja ete lu."""
    day = await target_day(session, now)
    view = await read_day(session, now, day)
    tz = ZoneInfo(view.timezone)
    expires = day_bounds(day, tz)[1]
    frame = view.plan.frame
    if frame is not None and frame.end is not None:
        expires = max(expires, frame.end)  # une nuit de travail
    return await prepare(
        session, user_id, "focus", KIND, day, title(day), sections(view), now, expires
    )


async def prepare_all(database: Database, now: datetime) -> dict[str, int]:
    """Tous les utilisateurs du Sergent, chacun sous sa RLS ; un echec n'arrete pas les autres."""
    async with database.transaction(None) as session:
        users = list(
            await session.scalars(
                text("SELECT user_id FROM lorakus.core_users_with_module('focus')")
            )
        )
    totals = {"users": len(users), "prepared": 0, "crashed": 0}
    for user in users:
        try:
            async with database.transaction(user) as session:
                if await prepare_briefing(session, user, now):
                    totals["prepared"] += 1
        except Exception:
            log.exception("briefing_crashed")
            totals["crashed"] += 1
    return totals


@periodic("focus.briefing", cron="*/15 * * * *")
async def briefing(ctx: JobContext, payload: dict[str, Any]) -> None:
    totals = await prepare_all(ctx.database, datetime.now(UTC))
    if totals["crashed"]:
        log.warning("briefing_round", **totals)
