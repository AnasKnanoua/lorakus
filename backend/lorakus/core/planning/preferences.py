"""Preferences de planification (PR 48, ADR 0018) : un catalogue ferme de reglages types.

Le planificateur a besoin de connaitre un peu la personne : quand elle travaille, quand elle
mange, quels jours elle ne travaille pas. Chaque preference est une cle d'un catalogue FERME,
avec une valeur typee et bornee : jamais du texte libre, jamais une regle inventee par un
modele. Sans preference confirmee, la valeur par defaut s'applique.

| Cle | Valeur | Defaut |
| --- | --- | --- |
| work_start | heure de debut de la journee de travail | 08:00 |
| work_end | heure limite : plus de travail propose apres | 22:00 |
| lunch | plage du dejeuner | aucune |
| dinner | plage du diner | aucune |
| rest_days | jours de la semaine sans travail propose | aucun |
| daily_cap | travail propose par jour, au plus | 6 h |

Rien n'entre ici sans confirmation de l'utilisateur : dans le chat, une carte (ADR 0040) ;
la valeur est revalidee a l'ecriture et a la lecture (une ligne illisible est ignoree, le
defaut s'applique : le planificateur ne tombe jamais a cause d'une preference).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import Any, Final, Literal, cast, get_args

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.identity.service import audit
from lorakus.core.planning.models import PlanningPreference

Key = Literal["work_start", "work_end", "lunch", "dinner", "rest_days", "daily_cap"]
KEYS: Final[tuple[Key, ...]] = get_args(Key)

MIN_WORK_WINDOW_MINUTES: Final = 60
MIN_MEAL_MINUTES: Final = 15
MAX_MEAL_MINUTES: Final = 180
MIN_DAILY_CAP_MINUTES: Final = 30
MAX_DAILY_CAP_MINUTES: Final = 12 * 60
DEFAULT_DAILY_CAP_MINUTES: Final = 6 * 60
# Jamais sept jours sans travail : le planificateur ne servirait plus a rien, en silence.
MAX_REST_DAYS: Final = 6

LABEL: Final[dict[Key, str]] = {
    "work_start": "Début de la journée de travail",
    "work_end": "Fin de la journée de travail",
    "lunch": "Déjeuner",
    "dinner": "Dîner",
    "rest_days": "Jours sans travail",
    "daily_cap": "Travail proposé par jour",
}
WEEKDAYS: Final = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


class InvalidPreferenceError(ValueError):
    """Valeur refusee ; le message est lisible par l'utilisateur."""


@dataclass(frozen=True)
class TimeRange:
    """Une plage d'heures murales dans la meme journee (debut inclus, fin exclue)."""

    start: time
    end: time

    @property
    def minutes(self) -> int:
        return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)


@dataclass(frozen=True)
class PlanningPrefs:
    """Les preferences telles que le planificateur les lit, defauts compris."""

    work_start: time = time(8, 0)
    work_end: time = time(22, 0)
    lunch: TimeRange | None = None
    dinner: TimeRange | None = None
    rest_days: frozenset[int] = frozenset()  # 0 : lundi ... 6 : dimanche
    daily_cap: int = DEFAULT_DAILY_CAP_MINUTES  # minutes


DEFAULTS: Final = PlanningPrefs()
Value = time | TimeRange | frozenset[int] | int


# ----------------------------------------------------------------- valeurs
def _time(raw: object) -> time:
    if not isinstance(raw, str):
        raise InvalidPreferenceError("Heure attendue, au format HH:MM.")
    try:
        parsed = time.fromisoformat(raw)
    except ValueError:
        raise InvalidPreferenceError("Heure attendue, au format HH:MM.") from None
    if len(raw) != 5 or parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise InvalidPreferenceError("Heure attendue, au format HH:MM.")
    return parsed


def _weekdays(raw: object) -> frozenset[int]:
    if not isinstance(raw, list) or not raw:
        raise InvalidPreferenceError("Donne au moins un jour de la semaine.")
    days: set[int] = set()
    for item in cast(list[object], raw):
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6:
            raise InvalidPreferenceError("Donne au moins un jour de la semaine.")
        days.add(item)
    return frozenset(days)


def parse_value(key: Key, raw: dict[str, Any]) -> Value:
    """Valeur typee d'une preference, depuis son objet JSON ; refuse tout ce qui deborde."""
    if key in ("work_start", "work_end"):
        return _time(raw.get("time"))
    if key in ("lunch", "dinner"):
        meal = TimeRange(_time(raw.get("start")), _time(raw.get("end")))
        if not MIN_MEAL_MINUTES <= meal.minutes <= MAX_MEAL_MINUTES:
            raise InvalidPreferenceError(
                "Un repas dure entre 15 minutes et 3 heures, et finit après avoir commencé."
            )
        return meal
    if key == "rest_days":
        listed: object = raw.get("days")
        days = _weekdays(listed)
        if len(days) > MAX_REST_DAYS:
            raise InvalidPreferenceError("Garde au moins un jour de travail dans la semaine.")
        return days
    minutes = raw.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise InvalidPreferenceError("Durée attendue, en minutes.")
    if not MIN_DAILY_CAP_MINUTES <= minutes <= MAX_DAILY_CAP_MINUTES:
        raise InvalidPreferenceError("Entre 30 minutes et 12 heures de travail par jour.")
    return minutes


def to_json(key: Key, value: Value) -> dict[str, Any]:
    """Objet JSON enregistre pour une valeur typee (l'inverse de `parse_value`)."""
    if isinstance(value, time):
        return {"time": value.strftime("%H:%M")}
    if isinstance(value, TimeRange):
        return {"start": value.start.strftime("%H:%M"), "end": value.end.strftime("%H:%M")}
    if isinstance(value, frozenset):
        return {"days": sorted(value)}
    return {"minutes": value}


def _with(prefs: PlanningPrefs, key: Key, value: Value | None) -> PlanningPrefs:
    return replace(prefs, **{key: value})


def check_together(prefs: PlanningPrefs) -> None:
    """Coherence de l'ensemble : la journee de travail doit durer au moins une heure."""
    window = TimeRange(prefs.work_start, prefs.work_end)
    if window.minutes < MIN_WORK_WINDOW_MINUTES:
        raise InvalidPreferenceError(
            "La journée de travail doit durer au moins une heure : "
            f"elle irait de {clock(prefs.work_start)} à {clock(prefs.work_end)}."
        )


# ------------------------------------------------------------------- texte
def clock(moment: time) -> str:
    """« 12 h 30 », « 8 h »."""
    return f"{moment.hour} h" if moment.minute == 0 else f"{moment.hour} h {moment.minute:02d}"


def _hours(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest} min"
    return f"{hours} h" if rest == 0 else f"{hours} h {rest:02d}"


def value_text(key: Key, value: Value | None) -> str:
    """La valeur d'une preference en francais, pour une carte, une page ou le modele."""
    if value is None:
        return "aucun" if key in ("lunch", "dinner", "rest_days") else ""
    if isinstance(value, time):
        return clock(value)
    if isinstance(value, TimeRange):
        return f"de {clock(value.start)} à {clock(value.end)}"
    if isinstance(value, frozenset):
        return ", ".join(WEEKDAYS[day] for day in sorted(value)) if value else "aucun"
    return f"{_hours(value)} au plus"


def current_value(prefs: PlanningPrefs, key: Key) -> Value | None:
    value: Value | None = getattr(prefs, key)
    return value


# -------------------------------------------------------------------- base
@dataclass(frozen=True)
class StoredPreference:
    key: Key
    value: Value
    updated_at: datetime


async def stored(session: AsyncSession) -> list[StoredPreference]:
    """Preferences confirmees de l'utilisateur de la session, lisibles, dans l'ordre du
    catalogue. Une ligne dont la valeur ne se lit plus est ignoree."""
    rows = {row.key: row for row in await session.scalars(select(PlanningPreference))}
    found: list[StoredPreference] = []
    for key in KEYS:
        row = rows.get(key)
        if row is None:
            continue
        try:
            found.append(StoredPreference(key, parse_value(key, row.value), row.updated_at))
        except InvalidPreferenceError:
            continue
    return found


async def load(session: AsyncSession) -> PlanningPrefs:
    """Preferences du planificateur : les confirmees, sinon les defauts.

    Si l'ensemble est incoherent (lignes modifiees hors du service), les defauts s'appliquent
    en entier : mieux vaut un plan ordinaire qu'aucun plan.
    """
    prefs = DEFAULTS
    for item in await stored(session):
        prefs = _with(prefs, item.key, item.value)
    try:
        check_together(prefs)
    except InvalidPreferenceError:
        return DEFAULTS
    return prefs


async def preview(
    session: AsyncSession, key: Key, raw: dict[str, Any]
) -> tuple[Value, Value | None]:
    """Valide une preference AVANT de la proposer : rend (nouvelle valeur, valeur actuelle).

    Refuse une valeur hors bornes, et une valeur qui rendrait l'ensemble incoherent.
    """
    value = parse_value(key, raw)
    prefs = await load(session)
    check_together(_with(prefs, key, value))
    return value, current_value(prefs, key)


async def set_preference(
    session: AsyncSession,
    user_id: uuid.UUID,
    key: Key,
    raw: dict[str, Any],
    *,
    source_ref: str | None = None,
    ip: str | None = None,
) -> Value:
    """Enregistre une preference confirmee par l'utilisateur (remplace l'ancienne)."""
    value, _ = await preview(session, key, raw)
    row = {
        "user_id": user_id,
        "key": key,
        "value": to_json(key, value),
        "source_kind": "conversation" if source_ref else "user",
        "source_ref": source_ref,
    }
    statement = insert(PlanningPreference).values(**row)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["user_id", "key"],
            set_={
                "value": statement.excluded.value,
                "source_kind": statement.excluded.source_kind,
                "source_ref": statement.excluded.source_ref,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await audit(session, user_id, "planning.preference_set", "success", ip, {"key": key})
    return value


async def clear_preference(
    session: AsyncSession, user_id: uuid.UUID, key: Key, ip: str | None = None
) -> bool:
    """Retire une preference : le defaut s'applique de nouveau. Rend False si elle n'existait
    pas. Refuse si le reste deviendrait incoherent (ex. fin a 9 h, et on retire le debut a 7 h)."""
    prefs = await load(session)
    check_together(_with(prefs, key, current_value(DEFAULTS, key)))
    result = await session.execute(
        delete(PlanningPreference)
        .where(PlanningPreference.key == key)
        .returning(PlanningPreference.key)
    )
    removed = result.first() is not None
    if removed:
        await audit(session, user_id, "planning.preference_clear", "success", ip, {"key": key})
    return removed
