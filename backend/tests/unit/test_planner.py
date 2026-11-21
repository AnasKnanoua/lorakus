"""Planificateur de journee (PR 47 et 49) : des regles pures, testees une a une puis ensemble.

Reperes : mercredi 18 novembre 2026 a Ankara (UTC+3, sans changement d'heure). Les heures
des tests sont des heures locales, converties par `at`. Le cadre du jour (days.py) donne la
plage de travail : sans cadre, rien n'est propose.
"""

import dataclasses
import itertools
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lorakus.core.planning import planner
from lorakus.core.planning.days import DayFrame, build_frame, day_off
from lorakus.core.planning.planner import (
    Block,
    Candidate,
    Interval,
    Leftover,
    busy_intervals,
    candidates,
    free_slots,
    place,
    plan_day,
    round_up,
    work_window,
)
from lorakus.core.planning.service import AgendaView, TaskView

ANKARA = ZoneInfo("Europe/Istanbul")
PARIS = ZoneInfo("Europe/Paris")
DAY = date(2026, 11, 18)
CREATED = datetime(2026, 11, 1, tzinfo=UTC)


def dice(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 (tirage reproductible d'un test, pas un secret)


def at(hour: int, minute: int = 0, day: date = DAY, tz: ZoneInfo = ANKARA) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(UTC)


def span(start: tuple[int, int], end: tuple[int, int]) -> Interval:
    return Interval(at(*start), at(*end))


def frame(
    start: tuple[int, int] = (8, 0),
    end: tuple[int, int] = (22, 0),
    breaks: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = (),
    day: date = DAY,
    tz: ZoneInfo = ANKARA,
) -> DayFrame:
    return build_frame(
        day,
        tz,
        time(*start),
        time(*end),
        [("meal", time(*b[0]), time(*b[1])) for b in breaks],
    )


FULL = frame()  # de 8 h a 22 h


def task(
    title: str = "Tache",
    *,
    due: date | None = None,
    minutes: int | None = 60,
    priority: int = 2,
    parent: uuid.UUID | None = None,
    open_subtasks: int = 0,
    subtasks: int | None = None,
    status: str = "open",
    created: datetime = CREATED,
    number: int | None = None,
) -> TaskView:
    return TaskView(
        id=uuid.UUID(int=number) if number is not None else uuid.uuid4(),
        title=title,
        notes=None,
        status=status,
        priority=priority,
        due_on=due,
        estimate_minutes=minutes,
        parent_id=parent,
        owner_module=None,
        owner_ref=None,
        source_kind="user",
        created_at=created,
        completed_at=None,
        open_subtasks=open_subtasks,
        subtasks=open_subtasks if subtasks is None else subtasks,
    )


def event(start: tuple[int, int], end: tuple[int, int], title: str = "Cours") -> AgendaView:
    return AgendaView(uuid.uuid4(), title, None, at(*start), at(*end), None, None, "calendars")


def all_day(title: str = "Ferie") -> AgendaView:
    return AgendaView(uuid.uuid4(), title, None, None, None, DAY, DAY + timedelta(days=1), None)


def one(minutes: int, title: str = "T") -> Candidate:
    return Candidate(task(title, minutes=minutes), None, minutes)


def hours(blocks: list[Block]) -> list[tuple[str, str]]:
    def local(moment: datetime) -> str:
        return moment.astimezone(ANKARA).strftime("%H:%M")

    return [(local(b.start), local(b.end)) for b in blocks]


# ------------------------------------------------------------ fenetre
def test_round_up_goes_to_the_next_quarter_and_keeps_an_exact_one() -> None:
    assert round_up(at(9, 0)) == at(9, 0)
    assert round_up(at(9, 1)) == at(9, 15)
    assert round_up(at(9, 15)) == at(9, 15)
    assert round_up(at(9, 46)) == at(10, 0)
    assert round_up(at(9, 0) + timedelta(seconds=1)) == at(9, 15)
    assert round_up(at(9, 0) + timedelta(microseconds=1)) == at(9, 15)
    assert round_up(at(23, 50)) == at(0, 0, DAY + timedelta(days=1))


def test_the_window_runs_from_now_to_the_end_of_the_frame() -> None:
    assert work_window(at(6, 30), FULL) == span((8, 0), (22, 0))  # avant le debut
    assert work_window(at(8, 0), FULL) == span((8, 0), (22, 0))
    assert work_window(at(13, 7), FULL) == span((13, 15), (22, 0))
    assert work_window(at(21, 45), FULL) == span((21, 45), (22, 0))
    # 8 h a Ankara n'est pas 8 h a Paris : le meme cadre dit dans un autre fuseau.
    paris = work_window(at(6, 30), frame(tz=PARIS))
    assert paris == Interval(at(8, 0, tz=PARIS), at(22, 0, tz=PARIS))
    assert paris != work_window(at(6, 30), FULL)


@pytest.mark.parametrize("now", [(21, 46), (22, 0), (23, 30)])
def test_no_window_once_the_frame_is_over(now: tuple[int, int]) -> None:
    assert work_window(at(*now), FULL) is None


def test_no_window_without_a_frame_or_on_a_day_off() -> None:
    # Aucune heure supposee : sans cadre, pas de fenetre, quelle que soit l'heure.
    assert work_window(at(10, 0), None) is None
    assert work_window(at(10, 0), day_off(DAY)) is None


def test_a_night_frame_runs_past_midnight() -> None:
    night = frame((22, 0), (4, 0))
    tomorrow = DAY + timedelta(days=1)
    assert work_window(at(21, 0), night) == Interval(at(22, 0), at(4, 0, tomorrow))
    assert work_window(at(2, 10, tomorrow), night) == Interval(
        at(2, 15, tomorrow), at(4, 0, tomorrow)
    )
    assert work_window(at(4, 0, tomorrow), night) is None


# ------------------------------------------------------------- agenda
def test_busy_time_is_clipped_merged_and_ignores_all_day_entries() -> None:
    window = span((8, 0), (22, 0))
    agenda = [
        event((6, 0), (9, 0)),  # commence avant la fenetre
        event((10, 0), (11, 0)),
        event((10, 30), (12, 0)),  # chevauche le precedent
        event((12, 0), (12, 30)),  # le touche
        event((14, 0), (15, 0)),
        event((14, 15), (14, 45)),  # contenu dans le precedent
        event((21, 0), (23, 30)),  # finit apres la fenetre
        event((5, 0), (8, 0)),  # finit quand la fenetre commence : hors fenetre
        event((22, 0), (23, 0)),  # commence quand elle finit : hors fenetre
        all_day(),
    ]
    dice(1).shuffle(agenda)
    assert busy_intervals(agenda, window) == [
        span((8, 0), (9, 0)),
        span((10, 0), (12, 30)),
        span((14, 0), (15, 0)),
        span((21, 0), (22, 0)),
    ]


def test_free_slots_are_the_gaps_of_at_least_a_quarter() -> None:
    window = span((8, 0), (22, 0))
    busy = [
        span((8, 0), (9, 0)),
        span((9, 14), (10, 0)),
        span((10, 15), (12, 0)),
        span((21, 50), (22, 0)),
    ]
    assert free_slots(window, busy) == [span((10, 0), (10, 15)), span((12, 0), (21, 50))]
    assert free_slots(window, []) == [window]
    assert free_slots(window, [window]) == []
    assert free_slots(window, [span((9, 0), (10, 0))]) == [
        span((8, 0), (9, 0)),
        span((10, 0), (22, 0)),
    ]


def test_an_entry_that_only_touches_the_window_is_not_busy_time() -> None:
    window = span((8, 0), (22, 0))
    assert busy_intervals([event((5, 0), (8, 0))], window) == []  # finit quand elle commence
    assert busy_intervals([event((22, 0), (23, 0))], window) == []  # commence quand elle finit
    assert busy_intervals([event((7, 0), (8, 1))], window) == [span((8, 0), (8, 1))]
    assert busy_intervals([event((21, 59), (23, 0))], window) == [span((21, 59), (22, 0))]


# ------------------------------------------------------------- taches
def test_tasks_are_ordered_by_due_date_then_priority_then_length_then_age() -> None:
    tasks = [
        task("sans echeance, haute", priority=1),
        # Plus ancienne que la courte : c'est bien la duree qui les departage, pas l'age.
        task(
            "vendredi, longue",
            due=date(2026, 11, 20),
            minutes=120,
            created=CREATED - timedelta(days=1),
        ),
        task("vendredi, courte", due=date(2026, 11, 20), minutes=30),
        task("vendredi, haute", due=date(2026, 11, 20), priority=1, minutes=180),
        task("en retard", due=date(2026, 11, 10), priority=3),
        task("aujourd'hui", due=DAY),
        task("recente", due=date(2026, 11, 25), created=CREATED + timedelta(days=2)),
        task("ancienne", due=date(2026, 11, 25), created=CREATED),
        task("sans echeance, normale"),
    ]
    for seed in range(5):
        dice(seed).shuffle(tasks)
        assert [c.task.title for c in candidates(tasks)] == [
            "en retard",
            "aujourd'hui",
            "vendredi, haute",
            "vendredi, courte",
            "vendredi, longue",
            "ancienne",
            "recente",
            "sans echeance, haute",
            "sans echeance, normale",
        ]


def test_equal_tasks_keep_a_stable_order() -> None:
    twins = [task("b", number=2), task("a", number=1), task("c", number=3)]
    assert [c.task.title for c in candidates(twins)] == ["a", "b", "c"]
    assert [c.task.title for c in candidates(twins[::-1])] == ["a", "b", "c"]


def test_steps_are_planned_instead_of_their_parent() -> None:
    parent = task("Projet", due=date(2026, 11, 20), minutes=600, open_subtasks=2)
    step = task("Etape 1", parent=parent.id, minutes=45)
    dated = task("Etape 2", parent=parent.id, due=DAY, minutes=None)
    orphan = task("Etape d'une tache absente de la liste", parent=uuid.uuid4(), minutes=20)
    done = task("Terminee", status="done")
    chosen = candidates([parent, step, dated, orphan, done])
    assert [(c.task.title, c.due_on, c.minutes) for c in chosen] == [
        ("Etape 2", DAY, None),  # sa propre echeance ; aucune duree
        ("Etape 1", date(2026, 11, 20), 45),  # l'echeance de sa tache
        ("Etape d'une tache absente de la liste", None, 20),
    ]


def test_steps_stay_together_in_their_order_with_their_tasks_priority() -> None:
    parent = task("Projet", due=date(2026, 11, 20), minutes=300, open_subtasks=3, priority=1)
    # Identifiants dans l'ordre inverse des etapes, meme date de creation : seul le rang
    # peut donner l'ordre.
    steps = [
        dataclasses.replace(task(title, parent=parent.id, minutes=m, number=10 - n), step_number=n)
        for n, (title, m) in enumerate([("Lire", 120), ("Coder", 30), ("Rédiger", 60)], 1)
    ]
    other = task("Autre urgent", due=date(2026, 11, 20), minutes=10, priority=2)
    chosen = candidates([other, steps[2], parent, steps[0], steps[1]])
    # La priorite haute du projet passe a ses etapes ; ensuite, leur rang, pas leur duree.
    assert [c.task.title for c in chosen] == ["Lire", "Coder", "Rédiger", "Autre urgent"]


def test_the_steps_of_two_tasks_never_interleave() -> None:
    first = task("A", due=DAY, minutes=60, open_subtasks=2, number=1)
    second = task("B", due=DAY, minutes=60, open_subtasks=2, number=2)
    steps = [
        dataclasses.replace(
            task(f"{p.title}{n}", parent=p.id, minutes=30, number=n * 10 + i), step_number=n
        )
        for i, p in enumerate([first, second], 1)
        for n in (1, 2)
    ]
    chosen = [c.task.title for c in candidates([*steps, first, second])]
    assert chosen == ["A1", "A2", "B1", "B2"]


def test_a_task_whose_steps_are_all_done_is_not_proposed_again() -> None:
    # Ses etapes sont faites : il reste a la marquer terminee, pas a refaire 10 h de travail.
    finished = task("Projet", minutes=600, open_subtasks=0, subtasks=3)
    whole = task("Rapport", minutes=60)
    assert [c.task.title for c in candidates([finished, whole])] == ["Rapport"]


# ---------------------------------------------------------- placement
def test_a_task_takes_the_first_free_time() -> None:
    blocks, left = place([span((9, 0), (12, 0))], [one(60, "a"), one(45, "b")])
    assert hours(blocks) == [("09:00", "10:00"), ("10:15", "11:00")]  # un quart d'heure de pause
    assert left == []


def test_a_long_task_is_cut_in_blocks_of_two_hours_with_breaks() -> None:
    long = one(300)
    blocks, left = place([span((8, 0), (22, 0))], [long])
    assert hours(blocks) == [("08:00", "10:00"), ("10:15", "12:15"), ("12:30", "13:30")]
    assert [b.minutes for b in blocks] == [120, 120, 60]
    assert left == []


def test_a_task_continues_in_the_next_slot() -> None:
    blocks, left = place([span((9, 0), (10, 0)), span((14, 0), (18, 0))], [one(180)])
    assert hours(blocks) == [("09:00", "10:00"), ("14:00", "16:00")]
    assert left == []


def test_a_block_too_short_to_move_forward_is_not_proposed_unless_it_finishes() -> None:
    short, wide = span((9, 0), (9, 20)), span((14, 0), (15, 0))
    # 20 minutes ne font pas avancer une tache d'une heure : elle attend le creneau suivant.
    blocks, _ = place([short, wide], [one(60, "longue")])
    assert hours(blocks) == [("14:00", "15:00")]
    # Mais une tache de 20 minutes y tient entiere, meme placee apres la longue.
    long, quick = one(60, "longue"), one(20, "rapide")
    blocks, left = place([short, wide], [long, quick])
    assert [(b.task_id, *hours([b])[0]) for b in blocks] == [
        (quick.task.id, "09:00", "09:20"),
        (long.task.id, "14:00", "15:00"),
    ]
    assert left == []
    # Limite exacte : 30 minutes suffisent ; 29 non.
    assert hours(place([span((9, 0), (9, 30))], [one(60)])[0]) == [("09:00", "09:30")]
    assert place([span((9, 0), (9, 29))], [one(60)])[0] == []
    # La fin d'une tache peut etre plus courte que 30 minutes.
    blocks, _ = place([span((9, 0), (12, 0))], [one(130)])
    assert [b.minutes for b in blocks] == [120, 10]


def test_what_does_not_fit_is_returned_with_the_time_left() -> None:
    first, second, third = one(90, "a"), one(120, "b"), one(30, "c")
    blocks, left = place([span((9, 0), (11, 0))], [first, second, third])
    assert hours(blocks) == [("09:00", "10:30")]  # il reste 15 minutes apres la pause
    assert left == [Leftover(second.task.id, 120), Leftover(third.task.id, 30)]
    partial = one(200)
    blocks, left = place([span((9, 0), (10, 0))], [partial])
    assert [b.minutes for b in blocks] == [60]
    assert left == [Leftover(partial.task.id, 140)]
    assert place([], [partial]) == ([], [Leftover(partial.task.id, 200)])


def test_a_slot_shrunk_under_a_quarter_disappears() -> None:
    # 9 h - 10 h 10 : apres 45 min et la pause il reste 10 minutes, qui ne sont plus un creneau.
    small = one(10, "petite")
    blocks, left = place([span((9, 0), (10, 10))], [one(45, "a"), small])
    assert hours(blocks) == [("09:00", "09:45")]
    assert left == [Leftover(small.task.id, 10)]
    # Avec un quart d'heure plein apres la pause, elle passe.
    blocks, left = place([span((9, 0), (10, 15))], [one(45, "a"), small])
    assert hours(blocks) == [("09:00", "09:45"), ("10:00", "10:10")]


def test_the_whole_window_can_be_used_when_the_user_says_so() -> None:
    # Aucun plafond cache : la plage dite par l'utilisateur est la seule limite.
    work = [one(120, str(n)) for n in range(5)]
    blocks, left = place([span((8, 0), (22, 0))], work)
    assert sum(b.minutes for b in blocks) == 600
    assert left == []


def test_blocks_come_back_in_chronological_order() -> None:
    long, quick = one(60, "longue"), one(15, "rapide")
    blocks, _ = place([span((9, 0), (9, 20)), span((14, 0), (15, 0))], [long, quick])
    assert [b.task_id for b in blocks] == [quick.task.id, long.task.id]


# ----------------------------------------------------------- journee
def test_a_day_is_planned_around_the_agenda() -> None:
    homework = task("ML : TP 2", due=date(2026, 11, 20), minutes=180)
    errand = task("Courses", minutes=30)
    late = task("Rapport", due=date(2026, 11, 16), minutes=60, priority=3)
    agenda = [event((9, 0), (12, 0)), event((13, 30), (15, 0)), all_day()]

    plan = plan_day(at(7, 40), FULL, agenda, [errand, homework, late])

    assert plan.frame == FULL
    assert plan.window == span((8, 0), (22, 0))
    assert list(plan.free) == [
        span((8, 0), (9, 0)),
        span((12, 0), (13, 30)),
        span((15, 0), (22, 0)),
    ]
    assert [c.task.title for c in plan.candidates] == ["Rapport", "ML : TP 2", "Courses"]
    assert [(b.task_id, *hours([b])[0]) for b in plan.blocks] == [
        (late.id, "08:00", "09:00"),  # le retard d'abord
        (homework.id, "12:00", "13:30"),
        (homework.id, "15:00", "16:30"),
        (errand.id, "16:45", "17:15"),
    ]
    assert plan.leftovers == ()
    assert plan.unestimated == ()
    assert plan.planned_minutes == 60 + 180 + 30


def test_a_task_without_duration_is_never_placed_but_listed_to_estimate() -> None:
    known = task("TP", due=date(2026, 11, 20), minutes=60)
    unknown = task("DM", due=DAY, minutes=None)
    later = task("Lecture", minutes=None)
    plan = plan_day(at(9, 0), FULL, [], [later, known, unknown])
    assert [c.task.title for c in plan.candidates] == ["TP"]
    assert [c.task.title for c in plan.unestimated] == ["DM", "Lecture"]  # meme ordre
    assert {b.task_id for b in plan.blocks} == {known.id}
    assert plan.leftovers == ()
    # Sans cadre non plus, elles restent « a estimer », jamais « sans place ».
    plan = plan_day(at(9, 0), None, [], [known, unknown])
    assert [c.task.title for c in plan.unestimated] == ["DM"]
    assert plan.leftovers == (Leftover(known.id, 60),)


def test_without_a_frame_nothing_is_planned_and_everything_is_left() -> None:
    homework = task("TP", minutes=120)
    plan = plan_day(at(10, 0), None, [], [homework])
    assert (plan.frame, plan.window, plan.free, plan.blocks) == (None, None, (), ())
    assert plan.leftovers == (Leftover(homework.id, 120),)
    assert plan.planned_minutes == 0


def test_no_work_is_proposed_on_a_day_off() -> None:
    homework = task("TP", minutes=60)
    off = day_off(DAY)
    plan = plan_day(at(9, 0), off, [], [homework])
    assert (plan.frame, plan.window, plan.blocks) == (off, None, ())
    assert plan.leftovers == (Leftover(homework.id, 60),)


def test_the_plan_starts_now_and_skips_what_is_already_over() -> None:
    homework = task("TP", minutes=120)
    agenda = [event((9, 0), (10, 0)), event((14, 0), (16, 0))]
    plan = plan_day(at(14, 20), FULL, agenda, [homework])  # pendant un cours
    assert hours(list(plan.blocks)) == [("16:00", "18:00")]
    plan = plan_day(at(10, 7), FULL, agenda, [homework])
    assert hours(list(plan.blocks)) == [("10:15", "12:15")]


def test_once_the_frame_is_over_nothing_is_planned() -> None:
    homework = task("TP", minutes=120)
    plan = plan_day(at(22, 10), FULL, [], [homework])
    assert (plan.window, plan.free, plan.blocks) == (None, (), ())
    assert plan.frame == FULL
    assert plan.leftovers == (Leftover(homework.id, 120),)


def test_breaks_are_kept_free() -> None:
    day = frame((10, 0), (22, 0), breaks=(((12, 30), (13, 30)), ((19, 0), (20, 0))))
    homework = task("TP", minutes=360)
    plan = plan_day(at(10, 0), day, [], [homework])
    assert list(plan.free) == [
        span((10, 0), (12, 30)),
        span((13, 30), (19, 0)),
        span((20, 0), (22, 0)),
    ]
    assert hours(list(plan.blocks)) == [
        ("10:00", "12:00"),
        ("13:30", "15:30"),
        ("15:45", "17:45"),
    ]
    for block in plan.blocks:
        for pause in day.breaks:
            assert block.end <= pause.start or block.start >= pause.end
    # Sans la pause, le meme travail passerait sur l'heure du repas.
    assert hours(list(plan_day(at(10, 0), frame((10, 0), (22, 0)), [], [homework]).blocks))[1] == (
        "12:15",
        "14:15",
    )


def test_a_break_and_a_class_that_overlap_are_one_busy_time() -> None:
    day = frame((10, 0), (22, 0), breaks=(((12, 30), (13, 30)),))
    plan = plan_day(at(10, 0), day, [event((11, 0), (13, 0))], [])
    assert list(plan.free) == [span((10, 0), (11, 0)), span((13, 30), (22, 0))]


def test_a_night_is_planned_past_midnight_around_a_late_meal() -> None:
    tomorrow = DAY + timedelta(days=1)
    night = frame((21, 0), (3, 0), breaks=(((23, 30), (0, 15)),))
    homework = task("Projet", minutes=240)
    plan = plan_day(at(21, 0), night, [], [homework])
    assert [(b.start, b.end) for b in plan.blocks] == [
        (at(21, 0), at(23, 0)),
        (at(0, 15, tomorrow), at(2, 15, tomorrow)),
    ]
    # Vu a 1 h du matin, la nuit continue : il reste la fin de la plage.
    plan = plan_day(at(1, 0, tomorrow), night, [], [homework])
    assert [(b.start, b.end) for b in plan.blocks] == [(at(1, 0, tomorrow), at(3, 0, tomorrow))]
    assert plan.leftovers == (Leftover(homework.id, 120),)


def test_the_same_inputs_always_give_the_same_plan() -> None:
    tasks = [
        task(str(n), due=DAY + timedelta(days=n % 3), minutes=30 + 15 * n, number=n + 1)
        for n in range(8)
    ]
    agenda = [event((9, 0), (10, 30)), event((13, 0), (14, 0))]
    reference = plan_day(at(7, 0), FULL, agenda, tasks)
    for seed in range(10):
        shuffled_tasks, shuffled_agenda = tasks[:], agenda[:]
        dice(seed).shuffle(shuffled_tasks)
        dice(seed).shuffle(shuffled_agenda)
        assert plan_day(at(7, 0), FULL, shuffled_agenda, shuffled_tasks) == reference


@pytest.mark.parametrize("seed", range(60))
def test_every_plan_respects_the_rules(seed: int) -> None:
    """Journees tirees au hasard (graine fixe) : les garanties tiennent toujours."""
    rng = dice(seed)
    agenda = []
    for _ in range(rng.randint(0, 7)):
        start = at(6, 0) + timedelta(minutes=rng.randint(0, 17 * 60))
        agenda.append(
            AgendaView(
                uuid.uuid4(),
                "x",
                None,
                start,
                start + timedelta(minutes=rng.randint(5, 240)),
                None,
                None,
                None,
            )
        )
    tasks = [
        task(
            str(n),
            due=rng.choice([None, DAY + timedelta(days=rng.randint(-5, 10))]),
            minutes=rng.choice([None, 5, 10, 25, 30, 45, 90, 120, 200, 400]),
            priority=rng.randint(1, 3),
        )
        for n in range(rng.randint(0, 12))
    ]
    first, length = rng.randint(0, 23), rng.randint(2, 19)  # heures ; parfois apres minuit
    offset = rng.randint(0, length - 1)  # une pause de 45 minutes qui tient dans la plage
    pauses = (((((first + offset) % 24), 0), (((first + offset) % 24), 45)),)
    day = frame((first, 0), ((first + length) % 24, 0), breaks=pauses if rng.random() < 0.5 else ())
    now = at(0, 0) + timedelta(minutes=rng.randint(0, 30 * 60), seconds=rng.randint(0, 59))

    plan = plan_day(now, day, agenda, tasks)

    wanted = {c.task.id: c.minutes for c in plan.candidates}
    left = {item.task_id: item.minutes for item in plan.leftovers}
    blocks = list(plan.blocks)
    assert day.start is not None and day.end is not None
    assert blocks == sorted(blocks, key=lambda b: b.start)
    for first_block, second in itertools.pairwise(blocks):
        # Jamais deux blocs en meme temps, et toujours la pause entre deux.
        assert second.start - first_block.end >= timedelta(minutes=planner.BREAK_MINUTES)
    for block in blocks:
        assert 0 < block.minutes <= planner.MAX_BLOCK_MINUTES
        assert block.start >= now
        assert day.start <= block.start and block.end <= day.end  # dans la plage dite
        assert any(slot.start <= block.start and block.end <= slot.end for slot in plan.free)
        for entry in agenda:  # jamais pendant un creneau de l'agenda
            assert entry.starts_at is not None and entry.ends_at is not None
            assert block.end <= entry.starts_at or block.start >= entry.ends_at
        for pause_time in day.breaks:  # ni pendant une pause
            assert block.end <= pause_time.start or block.start >= pause_time.end
    for task_id, minutes in wanted.items():
        assert minutes is not None
        done = sum(b.minutes for b in blocks if b.task_id == task_id)
        assert done + left.get(task_id, 0) == minutes  # rien de perdu, rien d'invente
    assert set(left) <= set(wanted) and all(m > 0 for m in left.values())
    assert {b.task_id for b in blocks} <= set(wanted)
    # Une tache sans duree n'est jamais placee.
    assert {c.task.id for c in plan.unestimated}.isdisjoint({b.task_id for b in blocks})
    assert all(c.minutes is None for c in plan.unestimated)
