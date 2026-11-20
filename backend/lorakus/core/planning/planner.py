"""Planificateur de journee (PR 47, ADR 0018, regle 4) : deterministe, et il PROPOSE.

Des fonctions pures : aucune base, aucun reseau, aucun LLM, aucune horloge cachee. Elles
recoivent l'instant present, le fuseau du compte, les creneaux de l'agenda et les taches
ouvertes, et rendent un plan. Rien n'est ecrit nulle part : le plan est recalcule a chaque
lecture (today.py), et l'agenda ne contient jamais que ce que ses sources y ont mis.

Regles, dans l'ordre ou elles s'appliquent :

1. **Fenetre de travail** : de 8 h a 22 h, heure du compte, a partir de maintenant (arrondi
   au quart d'heure suivant). Les deux bornes sont des preferences (preferences.py) ; un jour
   sans travail n'a pas de fenetre.
2. **Creneaux libres** : la fenetre moins les creneaux horaires de l'agenda et les repas
   (preferences), fusionnes s'ils se touchent. Une journee entiere (ferie, anniversaire)
   n'occupe pas d'heures. Un trou de moins d'un quart d'heure n'est pas un creneau.
3. **Quelles taches** : les taches ouvertes sans sous-tache ouverte (on travaille sur les
   etapes, pas sur leur titre). Une sous-tache sans echeance prend celle de sa tache.
4. **Ordre** : echeance la plus proche d'abord (donc les retards en tete), les taches sans
   echeance a la fin ; a echeance egale, priorite haute d'abord ; puis la plus courte ; puis
   la plus ancienne.
5. **Duree** : la duree estimee, sinon 30 minutes, signalees comme supposees.
6. **Placement** : dans l'ordre, chaque tache prend le premier temps libre. Un bloc dure
   2 h au plus et 30 minutes au moins (ou ce qui reste de la tache) ; un quart d'heure de
   pause suit chaque bloc ; une tache trop longue pour un creneau continue dans le suivant.
7. **Plafond** : 6 h de travail proposees par jour (preference). Ce qui ne tient pas est
   rendu avec le temps restant, jamais cache.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from lorakus.core.planning.preferences import DEFAULTS, PlanningPrefs, TimeRange
from lorakus.core.planning.service import AgendaView, TaskView

GRID_MINUTES: Final = 15
MIN_SLOT_MINUTES: Final = 15
MIN_BLOCK_MINUTES: Final = 30
MAX_BLOCK_MINUTES: Final = 120
BREAK_MINUTES: Final = 15
DEFAULT_ESTIMATE_MINUTES: Final = 30


@dataclass(frozen=True)
class Interval:
    """Un intervalle [start, end[ d'instants avec fuseau."""

    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Candidate:
    """Une tache a placer, avec ce que le planificateur en retient."""

    task: TaskView
    due_on: date | None  # la sienne, sinon celle de sa tache parente
    minutes: int
    assumed: bool  # True : aucune duree estimee, 30 minutes supposees


@dataclass(frozen=True)
class Block:
    """Un bloc de travail propose pour une tache."""

    task_id: uuid.UUID
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Leftover:
    """Ce qui n'a pas trouve de place aujourd'hui pour une tache."""

    task_id: uuid.UUID
    minutes: int


@dataclass(frozen=True)
class DayPlan:
    window: Interval | None  # None : journee de travail finie, ou jour sans travail
    rest_day: bool  # True : jour sans travail (preference)
    meals: tuple[tuple[str, Interval], ...]  # (« lunch » ou « dinner », plage du jour)
    free: tuple[Interval, ...]
    candidates: tuple[Candidate, ...]  # dans l'ordre de placement
    blocks: tuple[Block, ...]  # dans l'ordre chronologique
    leftovers: tuple[Leftover, ...]  # dans l'ordre de placement

    @property
    def planned_minutes(self) -> int:
        return sum(block.minutes for block in self.blocks)


def round_up(moment: datetime, minutes: int = GRID_MINUTES) -> datetime:
    """Le prochain multiple de `minutes` (l'instant lui-meme s'il tombe juste)."""
    floor = moment.replace(second=0, microsecond=0)
    floor -= timedelta(minutes=floor.minute % minutes)
    return floor if floor == moment else floor + timedelta(minutes=minutes)


def local_range(day: date, tz: ZoneInfo, hours: TimeRange) -> Interval:
    """Une plage d'heures murales du jour local `day`, en instants UTC."""
    return Interval(
        datetime.combine(day, hours.start, tzinfo=tz).astimezone(UTC),
        datetime.combine(day, hours.end, tzinfo=tz).astimezone(UTC),
    )


def work_window(
    now: datetime, day: date, tz: ZoneInfo, prefs: PlanningPrefs = DEFAULTS
) -> Interval | None:
    """Ce qu'il reste de la fenetre de travail du jour local `day` a l'instant `now`.

    Les bornes sont des heures murales du fuseau du compte, converties en UTC : la fenetre
    suit la vraie journee, meme un jour de changement d'heure. Aucune fenetre un jour sans
    travail.
    """
    if day.weekday() in prefs.rest_days:
        return None
    whole = local_range(day, tz, TimeRange(prefs.work_start, prefs.work_end))
    start = max(whole.start, round_up(now.astimezone(UTC)))
    return Interval(start, whole.end) if start < whole.end else None


def meals_of(day: date, tz: ZoneInfo, prefs: PlanningPrefs) -> list[tuple[str, Interval]]:
    """Les repas du jour (preferences), dans l'ordre de la journee."""
    found = [
        (name, local_range(day, tz, hours))
        for name, hours in (("lunch", prefs.lunch), ("dinner", prefs.dinner))
        if hours is not None
    ]
    return sorted(found, key=lambda meal: meal[1].start)


def busy_intervals(
    agenda: Sequence[AgendaView], window: Interval, extra: Sequence[Interval] = ()
) -> list[Interval]:
    """Temps occupe : creneaux horaires de l'agenda et plages `extra` (repas), limites a la
    fenetre et fusionnes s'ils se touchent."""
    taken = [
        Interval(entry.starts_at, entry.ends_at)
        for entry in agenda
        if entry.starts_at is not None and entry.ends_at is not None
    ]
    clipped = sorted(
        (
            Interval(max(interval.start, window.start), min(interval.end, window.end))
            for interval in [*taken, *extra]
            if interval.start < window.end and interval.end > window.start
        ),
        key=lambda interval: (interval.start, interval.end),
    )
    merged: list[Interval] = []
    for interval in clipped:
        if merged and interval.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


def free_slots(window: Interval, busy: Sequence[Interval]) -> list[Interval]:
    """La fenetre moins les intervalles occupes (tries, disjoints), trous trop courts exclus."""
    slots: list[Interval] = []
    cursor = window.start
    for interval in busy:
        slots.append(Interval(cursor, interval.start))
        cursor = interval.end
    slots.append(Interval(cursor, window.end))
    # Un trou vide (deux creneaux qui se suivent, bord de fenetre) tombe avec les trop courts.
    return [slot for slot in slots if slot.minutes >= MIN_SLOT_MINUTES]


def candidates(tasks: Sequence[TaskView]) -> list[Candidate]:
    """Taches a placer, dans l'ordre de placement (regles 3 a 5)."""
    by_id = {task.id: task for task in tasks}
    chosen: list[Candidate] = []
    for task in tasks:
        if task.status != "open" or task.open_subtasks > 0:
            continue
        parent = by_id.get(task.parent_id) if task.parent_id is not None else None
        due_on = task.due_on if task.due_on is not None else (parent.due_on if parent else None)
        assumed = task.estimate_minutes is None
        minutes = DEFAULT_ESTIMATE_MINUTES if assumed else (task.estimate_minutes or 0)
        chosen.append(Candidate(task, due_on, minutes, assumed))
    return sorted(
        chosen,
        key=lambda c: (
            c.due_on or date.max,  # sans echeance : a la fin
            c.task.priority,
            c.minutes,
            c.task.created_at,
            str(c.task.id),
        ),
    )


def place(
    slots: Sequence[Interval], ordered: Sequence[Candidate], cap: int = DEFAULTS.daily_cap
) -> tuple[list[Block], list[Leftover]]:
    """Place les taches dans les creneaux libres (regles 6 et 7)."""
    free = list(slots)
    blocks: list[Block] = []
    leftovers: list[Leftover] = []
    planned = 0
    pause = timedelta(minutes=BREAK_MINUTES)
    for candidate in ordered:
        remaining = candidate.minutes
        index = 0
        while remaining > 0 and index < len(free):
            slot = free[index]
            wanted = min(remaining, MAX_BLOCK_MINUTES, cap - planned)
            length = min(wanted, slot.minutes)
            # Un bloc trop court pour avancer n'est pas propose, sauf s'il finit la tache.
            # Plafond atteint : `wanted` vaut 0, plus aucun creneau ne convient.
            if length < min(MIN_BLOCK_MINUTES, remaining):
                index += 1
                continue
            end = slot.start + timedelta(minutes=length)
            blocks.append(Block(candidate.task.id, slot.start, end))
            remaining -= length
            planned += length
            rest = Interval(min(end + pause, slot.end), slot.end)
            if rest.minutes >= MIN_SLOT_MINUTES:
                free[index] = rest
            else:
                del free[index]
        if remaining > 0:
            leftovers.append(Leftover(candidate.task.id, remaining))
    return sorted(blocks, key=lambda block: block.start), leftovers


def plan_day(
    now: datetime,
    day: date,
    tz: ZoneInfo,
    agenda: Sequence[AgendaView],
    tasks: Sequence[TaskView],
    prefs: PlanningPrefs = DEFAULTS,
) -> DayPlan:
    """Le plan propose pour le jour local `day`, vu a l'instant `now`."""
    ordered = candidates(tasks)
    meals = meals_of(day, tz, prefs)
    rest_day = day.weekday() in prefs.rest_days
    window = work_window(now, day, tz, prefs)
    if window is None:
        everything = tuple(Leftover(c.task.id, c.minutes) for c in ordered)
        return DayPlan(None, rest_day, tuple(meals), (), tuple(ordered), (), everything)
    slots = free_slots(window, busy_intervals(agenda, window, [hours for _, hours in meals]))
    blocks, leftovers = place(slots, ordered, prefs.daily_cap)
    return DayPlan(
        window,
        rest_day,
        tuple(meals),
        tuple(slots),
        tuple(ordered),
        tuple(blocks),
        tuple(leftovers),
    )
