"""Temps de l'utilisateur (ADR 0018, amendement du 2026-11-18).

Tout instant est stocke en UTC ; le fuseau de l'utilisateur sert seulement a lire ces
instants « chez lui » : quel jour sommes-nous, ou commence et finit ce jour. Une journee
locale ne dure pas toujours 24 h (23 h ou 25 h aux changements d'heure) : ses bornes sont
calculees par le fuseau, jamais en ajoutant 24 h.
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE: Final = "Europe/Paris"
# Noms IANA : lettres, chiffres, « _ », « + », « - » et « / » (jamais « .. » ni chemin absolu).
_TZ_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$")
MAX_TZ_CHARS: Final = 64


class InvalidTimezoneError(ValueError):
    """Nom de fuseau inconnu ou mal forme."""


def parse_timezone(name: str) -> ZoneInfo:
    """Fuseau IANA valide, ou InvalidTimezoneError (jamais de repli silencieux)."""
    if len(name) > MAX_TZ_CHARS or not _TZ_NAME.fullmatch(name):
        raise InvalidTimezoneError(f"fuseau horaire inconnu : {name[:MAX_TZ_CHARS]}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidTimezoneError(f"fuseau horaire inconnu : {name}") from None


def local_today(now: datetime, tz: ZoneInfo) -> date:
    """Le jour qu'il est chez l'utilisateur a l'instant `now` (aware)."""
    return now.astimezone(tz).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Debut (inclus) et fin (exclue) du jour local `day`, en UTC."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)
