"""Lecture d'un fichier ICS et depliage des recurrences en creneaux concrets (PR 45).

L'agenda du Core ne contient que des creneaux concrets (ADR 0018, regle 3) : toute la
complexite des recurrences reste ici. La lecture passe par `icalendar` et le depliage par
`recurring-ical-events` (RRULE, RDATE, EXDATE, RECURRENCE-ID, fuseaux TZID et VTIMEZONE,
X-WR-TIMEZONE de Google) : choix argumente dans l'ADR 0041.

Le fichier vient d'Internet : c'est une donnee NON FIABLE (ADR 0012).
- Taille bornee avant d'arriver ici (client sortant), nombre d'evenements borne ici.
- Une recurrence plus dense que la journee (SECONDLY, MINUTELY, HOURLY) ou qui multiplie
  les heures (BYHOUR x BYMINUTE x BYSECOND > 24) est ignoree : elle pourrait produire des
  millions d'occurrences et bloquer le worker. Un emploi du temps n'en a jamais besoin.
- Titres et lieux ramenes a une ligne visible et bornee ; au modele, ils ne passent que par
  inert() (outil de lecture de l'agenda).
"""

import unicodedata
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, cast
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]

from lorakus.core.planning.service import (
    MAX_ENTRIES_PER_SOURCE,
    MAX_LOCATION_CHARS,
    MAX_TITLE_CHARS,
    AgendaItem,
)

MAX_EVENTS: Final = 5000  # composants VEVENT dans un fichier
MAX_TIMES_PER_PERIOD: Final = 24
ALLOWED_FREQUENCIES: Final = frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"})
UNTITLED: Final = "(Sans titre)"
# Un evenement horaire sans fin ni duree (une echeance a 23 h 59) garde une minute :
# l'agenda exige une fin apres le debut, et l'information reste visible.
INSTANT: Final = timedelta(minutes=1)


class InvalidCalendarError(ValueError):
    """Fichier illisible ou hors bornes. `code` est stable (statut enregistre)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedCalendar:
    items: list[AgendaItem]
    skipped: int  # series ignorees (recurrence trop dense, dates incoherentes)
    truncated: bool  # plus de creneaux que MAX_ENTRIES_PER_SOURCE dans la fenetre


def visible_line(value: object, limit: int) -> str:
    """Une ligne lisible : controles et separateurs remplaces, caracteres invisibles (format,
    inversion de sens) retires, espaces regroupes, longueur bornee."""
    text = unicodedata.normalize("NFC", str(value))
    kept = "".join(
        " " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c
        for c in text
        if unicodedata.category(c) != "Cf"
    )
    line = " ".join(kept.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _rules(component: icalendar.Component) -> list[dict[str, list[Any]]]:
    raw: Any = component.get("RRULE")
    if raw is None:
        return []
    items = cast(list[Any], raw) if isinstance(raw, list) else [raw]
    return [cast(dict[str, list[Any]], dict(item)) for item in items]


def too_dense(component: icalendar.Component) -> bool:
    """Vrai si une regle de recurrence risque de produire un nombre deraisonnable de dates."""
    for rule in _rules(component):
        frequencies = [str(f).upper() for f in rule.get("FREQ", [])]
        if not frequencies or any(f not in ALLOWED_FREQUENCIES for f in frequencies):
            return True
        times = 1
        for part in ("BYHOUR", "BYMINUTE", "BYSECOND"):
            times *= max(1, len(rule.get(part, [])))
        if times > MAX_TIMES_PER_PERIOD:
            return True
    return False


def _value(component: icalendar.Component, name: str) -> Any:
    prop: Any = component.get(name)
    return None if prop is None else prop.dt


def _aware(moment: datetime, tz: ZoneInfo) -> datetime:
    """Heure « flottante » (sans fuseau) : celle de l'utilisateur."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=tz)


def _item(component: icalendar.Component, tz: ZoneInfo) -> AgendaItem | None:
    """Creneau de l'occurrence, ou None si ses dates sont incoherentes."""
    start = _value(component, "DTSTART")
    end = _value(component, "DTEND")
    title = visible_line(component.get("SUMMARY", ""), MAX_TITLE_CHARS) or UNTITLED
    place = visible_line(component.get("LOCATION", ""), MAX_LOCATION_CHARS) or None
    uid = visible_line(component.get("UID", ""), 200) or uuid.uuid4().hex
    if isinstance(start, datetime):
        begin = _aware(start, tz).astimezone(UTC)
        finish = _aware(end, tz).astimezone(UTC) if isinstance(end, datetime) else None
        if finish is None or finish <= begin:
            finish = begin + INSTANT
        key = f"{uid}|{begin.isoformat()}"
        return AgendaItem(key, title, starts_at=begin, ends_at=finish, location=place)
    if isinstance(start, date):
        last = end if isinstance(end, date) and not isinstance(end, datetime) else None
        if last is None or last <= start:
            last = start + timedelta(days=1)
        key = f"{uid}|{start.isoformat()}"
        return AgendaItem(key, title, start_date=start, end_date=last, location=place)
    return None


def _overlaps(item: AgendaItem, start: datetime, end: datetime) -> bool:
    if item.starts_at is not None and item.ends_at is not None:
        return item.ends_at > start and item.starts_at < end
    if item.start_date is not None and item.end_date is not None:
        return item.end_date > start.date() and item.start_date <= end.date()
    return False


def parse_calendar(
    data: bytes, window_start: datetime, window_end: datetime, tz: ZoneInfo
) -> ParsedCalendar:
    """Creneaux concrets de la fenetre [window_start, window_end[ (instants avec fuseau)."""
    if not data.lstrip(b"\xef\xbb\xbf \t\r\n").upper().startswith(b"BEGIN:VCALENDAR"):
        raise InvalidCalendarError("not_calendar", "ce n'est pas un fichier de calendrier (ICS)")
    try:
        calendar = icalendar.Calendar.from_ical(data)
    except Exception:  # bibliotheque tierce : toute erreur de lecture se vaut
        raise InvalidCalendarError("unreadable", "fichier de calendrier illisible") from None
    events = [c for c in calendar.subcomponents if c.name == "VEVENT"]
    if len(events) > MAX_EVENTS:
        raise InvalidCalendarError("too_many_events", f"trop d'événements ({MAX_EVENTS} au plus)")

    # Une serie trop dense est retiree en entier (le maitre ET ses occurrences modifiees).
    dangerous = {str(e.get("UID", "")) for e in events if too_dense(e)}
    if dangerous:
        calendar.subcomponents = [
            c
            for c in calendar.subcomponents
            if not (c.name == "VEVENT" and str(c.get("UID", "")) in dangerous)
        ]
    items: list[AgendaItem] = []
    seen: set[str] = set()
    truncated = False
    skipped = len(dangerous)
    try:
        query: Any = recurring_ical_events.of(calendar, skip_bad_series=True)
        occurrences = cast(Iterator[icalendar.Component], query.after(window_start))
        for occurrence in occurrences:
            if str(occurrence.get("STATUS", "")).upper() == "CANCELLED":
                continue
            item = _item(occurrence, tz)
            if item is None:
                skipped += 1
                continue
            first = item.starts_at or datetime.combine(
                item.start_date or date.min, datetime.min.time(), tzinfo=tz
            )
            if first >= window_end:
                break  # occurrences triees par debut : la suite est hors fenetre
            if not _overlaps(item, window_start, window_end) or item.external_key in seen:
                continue
            if len(items) >= MAX_ENTRIES_PER_SOURCE:
                truncated = True
                break
            seen.add(item.external_key)
            items.append(item)
    except (ValueError, TypeError, OverflowError):
        raise InvalidCalendarError(
            "unreadable", "récurrences illisibles dans ce calendrier"
        ) from None
    return ParsedCalendar(items=items, skipped=skipped, truncated=truncated)
