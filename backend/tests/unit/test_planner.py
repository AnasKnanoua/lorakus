"""Planificateur de journee (PR 47) : des regles pures, testees une a une puis ensemble.

Reperes : mercredi 18 novembre 2026 a Ankara (UTC+3, sans changement d'heure). Les heures
des tests sont des heures locales, converties par `at`.
"""

import itertools
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lorakus.core.planning import planner
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
from lorakus.core.planning.preferences import DEFAULTS, PlanningPrefs, TimeRange
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


def task(
    title: str = "Tache",
    *,
    due: date | None = None,
    minutes: int | None = 60,
    priority: int = 2,
    parent: uuid.UUID | None = None,
    open_subtasks: int = 0,
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
    )


def event(start: tuple[int, int], end: tuple[int, int], title: str = "Cours") -> AgendaView:
    return AgendaView(uuid.uuid4(), title, None, at(*start), at(*end), None, None, "calendars")


def all_day(title: str = "Ferie") -> AgendaView:
    return AgendaView(uuid.uuid4(), title, None, None, None, DAY, DAY + timedelta(days=1), None)


def one(minutes: int, title: str = "T") -> Candidate:
    return Candidate(task(title, minutes=minutes), None, minutes, False)


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


def test_the_window_runs_from_now_to_ten_pm_in_the_account_timezone() -> None:
    assert work_window(at(6, 30), DAY, ANKARA) == span((8, 0), (22, 0))  # avant 8 h
    assert work_window(at(8, 0), DAY, ANKARA) == span((8, 0), (22, 0))
    assert work_window(at(13, 7), DAY, ANKARA) == span((13, 15), (22, 0))
    assert work_window(at(21, 45), DAY, ANKARA) == span((21, 45), (22, 0))
    # 8 h a Ankara n'est pas 8 h a Paris : le meme instant donne une autre fenetre.
    paris = work_window(at(6, 30), DAY, PARIS)
    assert paris == Interval(at(8, 0, tz=PARIS), at(22, 0, tz=PARIS))
    assert paris != work_window(at(6, 30), DAY, ANKARA)


@pytest.mark.parametrize("now", [(21, 46), (22, 0), (23, 30)])
def test_no_window_once_the_working_day_is_over(now: tuple[int, int]) -> None:
    assert work_window(at(*now), DAY, ANKARA) is None


def test_the_window_follows_wall_clock_time_on_clock_change_days() -> None:
    autumn, spring = date(2026, 10, 25), date(2027, 3, 28)  # Paris : 25 h, puis 23 h
    for day in (autumn, spring):
        midnight = datetime(day.year, day.month, day.day, 0, 30, tzinfo=PARIS)
        window = work_window(midnight, day, PARIS)
        assert window is not None
        assert window.start.astimezone(PARIS).strftime("%H:%M") == "08:00"
        assert window.end.astimezone(PARIS).strftime("%H:%M") == "22:00"
        assert window.minutes == 14 * 60  # le changement a lieu la nuit, avant 8 h


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
    assert [(c.task.title, c.due_on, c.minutes, c.assumed) for c in chosen] == [
        ("Etape 2", DAY, 30, True),  # sa propre echeance ; 30 minutes supposees
        ("Etape 1", date(2026, 11, 20), 45, False),  # l'echeance de sa tache
        ("Etape d'une tache absente de la liste", None, 20, False),
    ]


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


def test_no_more_than_six_hours_are_proposed() -> None:
    work = [one(120, str(n)) for n in range(5)]
    blocks, left = place([span((8, 0), (22, 0))], work)
    assert sum(b.minutes for b in blocks) == 360
    assert [b.minutes for b in blocks] == [120, 120, 120]
    assert left == [Leftover(work[3].task.id, 120), Leftover(work[4].task.id, 120)]
    # Le plafond coupe une tache en cours ; le reste est rendu.
    big, late = one(350, "grosse"), one(60, "apres")
    blocks, left = place([span((8, 0), (22, 0))], [big, late])
    assert [b.minutes for b in blocks] == [120, 120, 110]
    # Il reste 10 minutes sous le plafond : trop peu pour avancer une tache d'une heure.
    assert left == [Leftover(late.task.id, 60)]
    # Plafond atteint pile : meme cinq minutes de plus ne sont pas proposees.
    crumb = one(5, "miette")
    blocks, left = place([span((8, 0), (22, 0))], [*work[:3], crumb])
    assert sum(b.minutes for b in blocks) == 360
    assert left == [Leftover(crumb.task.id, 5)]
    tiny = one(10, "minuscule")
    blocks, left = place([span((8, 0), (22, 0))], [big, late, tiny])
    assert [b.minutes for b in blocks] == [120, 120, 110, 10]  # mais assez pour la finir, elle
    assert left == [Leftover(late.task.id, 60)]


def test_blocks_come_back_in_chronological_order() -> None:
    long, quick = one(60, "longue"), one(15, "rapide")
    blocks, _ = place([span((9, 0), (9, 20)), span((14, 0), (15, 0))], [long, quick])
    assert [b.task_id for b in blocks] == [quick.task.id, long.task.id]


# ----------------------------------------------------------- journee
def test_a_day_is_planned_around_the_agenda() -> None:
    homework = task("ML : TP 2", due=date(2026, 11, 20), minutes=180)
    errand = task("Courses", minutes=None)
    late = task("Rapport", due=date(2026, 11, 16), minutes=60, priority=3)
    agenda = [event((9, 0), (12, 0)), event((13, 30), (15, 0)), all_day()]

    plan = plan_day(at(7, 40), DAY, ANKARA, agenda, [errand, homework, late])

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
        (errand.id, "16:45", "17:15"),  # 30 minutes supposees
    ]
    assert plan.leftovers == ()
    assert plan.planned_minutes == 60 + 180 + 30


def test_the_plan_starts_now_and_skips_what_is_already_over() -> None:
    homework = task("TP", minutes=120)
    agenda = [event((9, 0), (10, 0)), event((14, 0), (16, 0))]
    plan = plan_day(at(14, 20), DAY, ANKARA, agenda, [homework])  # pendant un cours
    assert hours(list(plan.blocks)) == [("16:00", "18:00")]
    plan = plan_day(at(10, 7), DAY, ANKARA, agenda, [homework])
    assert hours(list(plan.blocks)) == [("10:15", "12:15")]


def test_after_ten_pm_nothing_is_planned_and_everything_is_left() -> None:
    homework = task("TP", minutes=120)
    plan = plan_day(at(22, 10), DAY, ANKARA, [], [homework])
    assert (plan.window, plan.rest_day, plan.free, plan.blocks) == (None, False, (), ())
    assert plan.leftovers == (Leftover(homework.id, 120),)
    assert plan.planned_minutes == 0


def test_the_same_inputs_always_give_the_same_plan() -> None:
    tasks = [
        task(str(n), due=DAY + timedelta(days=n % 3), minutes=30 + 15 * n, number=n + 1)
        for n in range(8)
    ]
    agenda = [event((9, 0), (10, 30)), event((13, 0), (14, 0))]
    reference = plan_day(at(7, 0), DAY, ANKARA, agenda, tasks)
    for seed in range(10):
        shuffled_tasks, shuffled_agenda = tasks[:], agenda[:]
        dice(seed).shuffle(shuffled_tasks)
        dice(seed).shuffle(shuffled_agenda)
        assert plan_day(at(7, 0), DAY, ANKARA, shuffled_agenda, shuffled_tasks) == reference


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
    now = at(5, 0) + timedelta(minutes=rng.randint(0, 18 * 60), seconds=rng.randint(0, 59))

    plan = plan_day(now, DAY, ANKARA, agenda, tasks)

    wanted = {c.task.id: c.minutes for c in plan.candidates}
    left = {item.task_id: item.minutes for item in plan.leftovers}
    blocks = list(plan.blocks)
    assert plan.planned_minutes <= DEFAULTS.daily_cap
    assert blocks == sorted(blocks, key=lambda b: b.start)
    for first, second in itertools.pairwise(blocks):
        # Jamais deux blocs en meme temps, et toujours la pause entre deux.
        assert second.start - first.end >= timedelta(minutes=planner.BREAK_MINUTES)
    for block in blocks:
        assert 0 < block.minutes <= planner.MAX_BLOCK_MINUTES
        assert block.start >= now
        assert any(slot.start <= block.start and block.end <= slot.end for slot in plan.free)
        for entry in agenda:  # jamais pendant un creneau de l'agenda
            assert entry.starts_at is not None and entry.ends_at is not None
            assert block.end <= entry.starts_at or block.start >= entry.ends_at
    for task_id, minutes in wanted.items():
        done = sum(b.minutes for b in blocks if b.task_id == task_id)
        assert done + left.get(task_id, 0) == minutes  # rien de perdu, rien d'invente
    assert set(left) <= set(wanted) and all(m > 0 for m in left.values())
    assert {b.task_id for b in blocks} <= set(wanted)


# -------------------------------------------------- preferences (PR 48)
def test_the_window_follows_the_work_hours_preference() -> None:
    prefs = PlanningPrefs(work_start=time(10, 30), work_end=time(19, 0))
    assert work_window(at(6, 0), DAY, ANKARA, prefs) == span((10, 30), (19, 0))
    assert work_window(at(12, 5), DAY, ANKARA, prefs) == span((12, 15), (19, 0))
    assert work_window(at(19, 0), DAY, ANKARA, prefs) is None
    assert work_window(at(20, 0), DAY, ANKARA) is not None  # sans preference : jusqu'a 22 h


def test_no_work_is_proposed_on_a_rest_day() -> None:
    homework = task("TP", minutes=60)
    wednesday = PlanningPrefs(rest_days=frozenset({2}))  # le 18 novembre 2026 est un mercredi
    plan = plan_day(at(9, 0), DAY, ANKARA, [], [homework], wednesday)
    assert (plan.window, plan.rest_day, plan.blocks) == (None, True, ())
    assert plan.leftovers == (Leftover(homework.id, 60),)
    # Un autre jour de repos ne change rien a ce mercredi.
    sunday = PlanningPrefs(rest_days=frozenset({6}))
    plan = plan_day(at(9, 0), DAY, ANKARA, [], [homework], sunday)
    assert (plan.rest_day, hours(list(plan.blocks))) == (False, [("09:00", "10:00")])
    # Le jour local decide : a 23 h UTC mardi, il est deja mercredi a Ankara.
    late = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)
    assert plan_day(late, DAY, ANKARA, [], [homework], wednesday).rest_day is True


def test_meals_are_kept_free_and_listed_in_order() -> None:
    prefs = PlanningPrefs(
        lunch=TimeRange(time(12, 30), time(13, 30)), dinner=TimeRange(time(19, 0), time(20, 0))
    )
    homework = task("TP", minutes=360)
    plan = plan_day(at(10, 0), DAY, ANKARA, [], [homework], prefs)
    assert [(name, *hours([Block(homework.id, m.start, m.end)])[0]) for name, m in plan.meals] == [
        ("lunch", "12:30", "13:30"),
        ("dinner", "19:00", "20:00"),
    ]
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
        for _, meal in plan.meals:
            assert block.end <= meal.start or block.start >= meal.end
    # Sans la preference, le meme travail passerait sur l'heure du dejeuner.
    assert hours(list(plan_day(at(10, 0), DAY, ANKARA, [], [homework]).blocks))[1] == (
        "12:15",
        "14:15",
    )


def test_a_meal_and_a_class_that_overlap_are_one_busy_time() -> None:
    prefs = PlanningPrefs(lunch=TimeRange(time(12, 30), time(13, 30)))
    agenda = [event((11, 0), (13, 0))]
    plan = plan_day(at(10, 0), DAY, ANKARA, agenda, [], prefs)
    assert list(plan.free) == [span((10, 0), (11, 0)), span((13, 30), (22, 0))]
    # Un repas hors de la fenetre de travail reste affiche, sans rien bloquer.
    early = PlanningPrefs(lunch=TimeRange(time(6, 0), time(7, 0)))
    plan = plan_day(at(5, 0), DAY, ANKARA, [], [], early)
    assert (len(plan.meals), list(plan.free)) == (1, [span((8, 0), (22, 0))])


def test_the_daily_cap_preference_replaces_six_hours() -> None:
    work = [task(str(n), minutes=120, number=n + 1) for n in range(4)]
    short = plan_day(at(8, 0), DAY, ANKARA, [], work, PlanningPrefs(daily_cap=150))
    assert [b.minutes for b in short.blocks] == [120, 30]
    assert short.planned_minutes == 150
    long = plan_day(at(8, 0), DAY, ANKARA, [], work, PlanningPrefs(daily_cap=480))
    assert long.planned_minutes == 480 and long.leftovers == ()
