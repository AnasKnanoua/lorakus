"""Cadre du jour (PR 49, ADR 0018) : quand l'utilisateur travaille AUJOURD'HUI.

Les horaires de l'utilisateur changent tous les jours (manger a 18 h ou a 22 h, ou pas,
nuit blanche...). Le planificateur ne suppose donc aucune heure : il lit le cadre que
l'utilisateur donne pour UN jour, le plus souvent en le disant a Lorakus (« je bosse de
15 h a 3 h, je mange vers 22 h »). Sans cadre, aucun creneau n'est propose.

Un cadre est soit un jour sans travail, soit une plage de travail et ses pauses :

- la plage commence le jour dit, dans le fuseau du compte ; si la fin est plus tot que le
  debut, elle tombe le lendemain (« de 22 h a 4 h ») ; de 30 minutes a 20 heures ;
- une pause (repas, pause, sport, autre) tient dans la plage, de 10 minutes a 4 heures ;
  6 au plus.

Les heures sont converties en instants UTC une fois pour toutes. Rien n'est enregistre sans
confirmation (une carte du chat, ADR 0040). La ligne est revalidee a la lecture : une ligne
illisible compte comme absente, et le planificateur ne tombe jamais a cause d'elle.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal, cast, get_args
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import local_today
from lorakus.core.account.dates import duration
from lorakus.core.identity.service import audit
from lorakus.core.planning.models import PlanningDay

BreakKind = Literal["meal", "break", "sport", "other"]
BREAK_KINDS: Final[tuple[BreakKind, ...]] = get_args(BreakKind)
BREAK_LABEL: Final[dict[BreakKind, str]] = {
    "meal": "Repas",
    "break": "Pause",
    "sport": "Sport",
    "other": "Occupé",
}

MIN_FRAME_MINUTES: Final = 30
MAX_FRAME_MINUTES: Final = 20 * 60
MIN_BREAK_MINUTES: Final = 10
MAX_BREAK_MINUTES: Final = 4 * 60
MAX_BREAKS: Final = 6
_DAY: Final = 24 * 60


class InvalidFrameError(ValueError):
    """Cadre refuse ; le message est lisible par l'utilisateur."""


@dataclass(frozen=True)
class Pause:
    """Un temps sans travail dans la plage : [start, end[, instants UTC."""

    kind: BreakKind
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DayFrame:
    """Le cadre d'un jour local. `off` : pas de travail ; sinon `start` et `end` sont donnes."""

    day: date
    off: bool
    start: datetime | None = None
    end: datetime | None = None
    breaks: tuple[Pause, ...] = ()


# ------------------------------------------------------------ construction
def _at(day: date, moment: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, moment, tzinfo=tz).astimezone(UTC)


def _wall_minutes(start: time, end: time) -> int:
    """Minutes d'horloge de `start` a `end`, en passant minuit si besoin (0 : meme heure)."""
    return ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) % _DAY


def day_off(day: date) -> DayFrame:
    return DayFrame(day, off=True)


def build_frame(
    day: date,
    tz: ZoneInfo,
    start: time,
    end: time,
    breaks: Sequence[tuple[BreakKind, time, time]] = (),
) -> DayFrame:
    """Le cadre « de `start` a `end` » du jour `day`, avec ses pauses ; refuse tout ce qui
    deborde, avec un message pour l'utilisateur."""
    begin = _at(day, start, tz)
    finish = _at(day, end, tz)
    if finish <= begin:  # « de 22 h a 4 h » : la fin tombe le lendemain
        finish = _at(day + timedelta(days=1), end, tz)
    length = int((finish - begin).total_seconds() // 60)
    if not MIN_FRAME_MINUTES <= length <= MAX_FRAME_MINUTES:
        raise InvalidFrameError("Une plage de travail dure de 30 minutes à 20 heures.")
    if len(breaks) > MAX_BREAKS:
        raise InvalidFrameError(f"{MAX_BREAKS} pauses au plus dans une journée.")
    pauses: list[Pause] = []
    for kind, pause_start, pause_end in breaks:
        minutes = _wall_minutes(pause_start, pause_end)
        if not MIN_BREAK_MINUTES <= minutes <= MAX_BREAK_MINUTES:
            raise InvalidFrameError("Une pause dure de 10 minutes à 4 heures.")
        # La pause a lieu le jour dit ou le lendemain : celle qui tombe dans la plage.
        found = [
            moment
            for moment in (_at(day, pause_start, tz), _at(day + timedelta(days=1), pause_start, tz))
            if begin <= moment < finish
        ]
        if not found or found[0] + timedelta(minutes=minutes) > finish:
            raise InvalidFrameError(
                f"La pause de {clock(pause_start)} à {clock(pause_end)} "
                "n'est pas dans la plage de travail."
            )
        pauses.append(Pause(kind, found[0], found[0] + timedelta(minutes=minutes)))
    pauses.sort(key=lambda pause: (pause.start, pause.end))
    return DayFrame(day, False, begin, finish, tuple(pauses))


def check_not_over(frame: DayFrame, now: datetime) -> None:
    """Un cadre dont la plage est deja finie ne sert a rien : refuse."""
    if frame.end is not None and frame.end <= now:
        raise InvalidFrameError("Cette plage de travail est déjà passée.")


# ------------------------------------------------------------------- texte
def clock(moment: time) -> str:
    """« 12 h 30 », « 8 h »."""
    return f"{moment.hour} h" if moment.minute == 0 else f"{moment.hour} h {moment.minute:02d}"


def local_clock(moment: datetime, tz: ZoneInfo) -> str:
    return clock(moment.astimezone(tz).time())


def frame_lines(frame: DayFrame, tz: ZoneInfo) -> list[str]:
    """Le cadre en francais, une ligne par element : pour une carte, une page ou le modele."""
    if frame.off or frame.start is None or frame.end is None:
        return ["Pas de travail ce jour-là"]
    end_day = frame.end.astimezone(tz).date()
    after = " (le lendemain)" if end_day > frame.day else ""
    lines = [
        f"Travail : de {local_clock(frame.start, tz)} à {local_clock(frame.end, tz)}{after}"
        f" ({duration(int((frame.end - frame.start).total_seconds() // 60))})"
    ]
    lines.extend(
        f"{BREAK_LABEL[pause.kind]} : de {local_clock(pause.start, tz)} "
        f"à {local_clock(pause.end, tz)}"
        for pause in frame.breaks
    )
    return lines


# -------------------------------------------------------------------- base
def _breaks_json(frame: DayFrame) -> list[dict[str, str]]:
    return [
        {"kind": p.kind, "start": p.start.isoformat(), "end": p.end.isoformat()}
        for p in frame.breaks
    ]


def _instant(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise InvalidFrameError("instant illisible")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise InvalidFrameError("instant sans fuseau")
    return moment.astimezone(UTC)


def read_row(row: PlanningDay) -> DayFrame | None:
    """Le cadre d'une ligne, revalide ; None si la ligne ne se lit plus (elle compte alors
    comme absente)."""
    if row.off:
        return day_off(row.day)
    if row.starts_at is None or row.ends_at is None:
        return None
    try:
        start, end = row.starts_at.astimezone(UTC), row.ends_at.astimezone(UTC)
        if not MIN_FRAME_MINUTES * 60 <= (end - start).total_seconds() <= MAX_FRAME_MINUTES * 60:
            return None
        raw = row.breaks  # JSON : revalide, la base ne garantit que « un tableau »
        if not isinstance(raw, list) or len(cast(list[object], raw)) > MAX_BREAKS:
            return None
        pauses: list[Pause] = []
        for item in cast(list[object], raw):
            if not isinstance(item, dict):
                return None
            fields = cast(dict[str, Any], item)
            kind = fields.get("kind")
            if kind not in BREAK_KINDS:
                return None
            begin, finish = _instant(fields.get("start")), _instant(fields.get("end"))
            pause = Pause(kind, begin, finish)
            if not (start <= pause.start < pause.end <= end):
                return None
            pauses.append(pause)
    except (InvalidFrameError, ValueError):
        return None
    pauses.sort(key=lambda pause: (pause.start, pause.end))
    return DayFrame(row.day, False, start, end, tuple(pauses))


async def get_frame(session: AsyncSession, day: date) -> DayFrame | None:
    row = await session.scalar(select(PlanningDay).where(PlanningDay.day == day))
    return None if row is None else read_row(row)


async def current_day(session: AsyncSession, now: datetime, tz: ZoneInfo) -> date:
    """Le jour « en cours » : celui d'hier si sa plage de travail n'est pas finie (nuit
    blanche), sinon le jour local."""
    today = local_today(now, tz)
    yesterday = await get_frame(session, today - timedelta(days=1))
    if yesterday is not None and yesterday.end is not None and yesterday.end > now:
        return yesterday.day
    return today


async def set_frame(
    session: AsyncSession,
    user_id: uuid.UUID,
    frame: DayFrame,
    *,
    source_ref: str | None = None,
    ip: str | None = None,
) -> None:
    """Enregistre le cadre d'un jour, confirme par l'utilisateur (remplace l'ancien)."""
    row: dict[str, Any] = {
        "user_id": user_id,
        "day": frame.day,
        "off": frame.off,
        "starts_at": frame.start,
        "ends_at": frame.end,
        "breaks": _breaks_json(frame),
        "source_kind": "conversation" if source_ref else "user",
        "source_ref": source_ref,
    }
    statement = insert(PlanningDay).values(**row)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "day"],
            set_={
                "off": statement.excluded.off,
                "starts_at": statement.excluded.starts_at,
                "ends_at": statement.excluded.ends_at,
                "breaks": statement.excluded.breaks,
                "source_kind": statement.excluded.source_kind,
                "source_ref": statement.excluded.source_ref,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await audit(session, user_id, "planning.day_set", "success", ip, {"day": frame.day.isoformat()})


async def clear_frame(
    session: AsyncSession, user_id: uuid.UUID, day: date, ip: str | None = None
) -> bool:
    """Efface le cadre d'un jour ; False s'il n'y en avait pas."""
    result = await session.execute(
        delete(PlanningDay).where(PlanningDay.day == day).returning(PlanningDay.day)
    )
    removed = result.first() is not None
    if removed:
        await audit(session, user_id, "planning.day_clear", "success", ip, {"day": day.isoformat()})
    return removed
