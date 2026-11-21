"""Planificateur de journee (PR 47 et 49, ADR 0018) : deterministe, et il PROPOSE.

Des fonctions pures : aucune base, aucun reseau, aucun LLM, aucune horloge cachee. Elles
recoivent l'instant present, le cadre du jour, les creneaux de l'agenda et les taches
ouvertes, et rendent un plan. Rien n'est ecrit nulle part : le plan est recalcule a chaque
lecture (today.py), et l'agenda ne contient jamais que ce que ses sources y ont mis.

Regles, dans l'ordre ou elles s'appliquent :

1. **Fenetre de travail** : la plage que l'utilisateur a donnee pour ce jour (days.py), a
   partir de maintenant (arrondi au quart d'heure suivant). Sans cadre, ou un jour sans
   travail : aucune fenetre, aucun creneau propose. Aucune heure n'est jamais supposee.
2. **Creneaux libres** : la fenetre moins les creneaux horaires de l'agenda et les pauses du
   cadre (repas, sport...), fusionnes s'ils se touchent. Une journee entiere (ferie,
   anniversaire) n'occupe pas d'heures. Un trou de moins d'un quart d'heure n'est pas un
   creneau.
3. **Quelles taches** : les taches ouvertes sans sous-tache ouverte (on travaille sur les
   etapes, pas sur leur titre). Une sous-tache sans echeance prend celle de sa tache.
4. **Duree** : la duree estimee. Une tache SANS duree n'est pas placee : elle est rendue a
   part (« a estimer »), pour que Lorakus demande combien de temps elle prendra au lieu de
   supposer.
5. **Ordre** : echeance la plus proche d'abord (donc les retards en tete), les taches sans
   echeance a la fin ; a echeance egale, priorite haute d'abord ; puis la plus courte ; puis
   la plus ancienne.
6. **Placement** : dans l'ordre, chaque tache prend le premier temps libre. Un bloc dure
   2 h au plus et 30 minutes au moins (ou ce qui reste de la tache) ; un quart d'heure de
   pause suit chaque bloc ; une tache trop longue pour un creneau continue dans le suivant.
   Ce qui ne tient pas dans la fenetre est rendu avec le temps restant, jamais cache.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final

from lorakus.core.planning.days import DayFrame
from lorakus.core.planning.service import AgendaView, TaskView

GRID_MINUTES: Final = 15
MIN_SLOT_MINUTES: Final = 15
MIN_BLOCK_MINUTES: Final = 30
MAX_BLOCK_MINUTES: Final = 120
BREAK_MINUTES: Final = 15


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
    minutes: int | None  # None : aucune duree estimee, la tache n'est pas placee


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
    frame: DayFrame | None  # None : l'utilisateur n'a rien dit pour ce jour
    window: Interval | None  # None : pas de cadre, jour sans travail, ou plage finie
    free: tuple[Interval, ...]
    candidates: tuple[Candidate, ...]  # avec une duree, dans l'ordre de placement
    unestimated: tuple[Candidate, ...]  # sans duree, dans le meme ordre : a estimer
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


def work_window(now: datetime, frame: DayFrame | None) -> Interval | None:
    """Ce qu'il reste de la plage de travail du cadre a l'instant `now` ; None sans cadre, un
    jour sans travail, ou une fois la plage finie."""
    if frame is None or frame.start is None or frame.end is None:
        return None
    start = max(frame.start, round_up(now.astimezone(UTC)))
    return Interval(start, frame.end) if start < frame.end else None


def busy_intervals(
    agenda: Sequence[AgendaView], window: Interval, extra: Sequence[Interval] = ()
) -> list[Interval]:
    """Temps occupe : creneaux horaires de l'agenda et plages `extra` (pauses du cadre),
    limites a la fenetre et fusionnes s'ils se touchent."""
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
    """Taches a placer ou a estimer, dans l'ordre de placement (regles 3 a 5)."""
    by_id = {task.id: task for task in tasks}
    chosen: list[Candidate] = []
    for task in tasks:
        if task.status != "open" or task.open_subtasks > 0:
            continue
        parent = by_id.get(task.parent_id) if task.parent_id is not None else None
        due_on = task.due_on if task.due_on is not None else (parent.due_on if parent else None)
        chosen.append(Candidate(task, due_on, task.estimate_minutes))
    return sorted(
        chosen,
        key=lambda c: (
            c.due_on or date.max,  # sans echeance : a la fin
            c.task.priority,
            c.minutes or 0,
            c.task.created_at,
            str(c.task.id),
        ),
    )


def place(
    slots: Sequence[Interval], ordered: Sequence[Candidate]
) -> tuple[list[Block], list[Leftover]]:
    """Place les taches (avec une duree) dans les creneaux libres (regle 6)."""
    free = list(slots)
    blocks: list[Block] = []
    leftovers: list[Leftover] = []
    pause = timedelta(minutes=BREAK_MINUTES)
    for candidate in ordered:
        remaining = candidate.minutes or 0
        index = 0
        while remaining > 0 and index < len(free):
            slot = free[index]
            length = min(remaining, MAX_BLOCK_MINUTES, slot.minutes)
            # Un bloc trop court pour avancer n'est pas propose, sauf s'il finit la tache.
            if length < min(MIN_BLOCK_MINUTES, remaining):
                index += 1
                continue
            end = slot.start + timedelta(minutes=length)
            blocks.append(Block(candidate.task.id, slot.start, end))
            remaining -= length
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
    frame: DayFrame | None,
    agenda: Sequence[AgendaView],
    tasks: Sequence[TaskView],
) -> DayPlan:
    """Le plan propose pour le jour du cadre `frame`, vu a l'instant `now`."""
    every = candidates(tasks)
    known = tuple(c for c in every if c.minutes is not None)
    unknown = tuple(c for c in every if c.minutes is None)
    window = work_window(now, frame)
    if window is None:
        everything = tuple(Leftover(c.task.id, c.minutes or 0) for c in known)
        return DayPlan(frame, None, (), known, unknown, (), everything)
    pauses = [] if frame is None else [Interval(p.start, p.end) for p in frame.breaks]
    slots = free_slots(window, busy_intervals(agenda, window, pauses))
    blocks, leftovers = place(slots, known)
    return DayPlan(frame, window, tuple(slots), known, unknown, tuple(blocks), tuple(leftovers))
