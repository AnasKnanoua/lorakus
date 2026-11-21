"""Politique d'intervention (ADR 0042) : chaque regle, puis des semaines simulees.

Horloge fixe. Repere : lundi 23 novembre 2026, Ankara (UTC+3).
"""

import random
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lorakus.core.account.clock import day_bounds
from lorakus.core.planning.days import DayFrame, build_frame, day_off
from lorakus.core.signals.policy import (
    DAILY_PUSH_BUDGET,
    LEVEL1_IGNORED_AFTER,
    RECHECK,
    TEST_SIGNAL,
    Decision,
    SignalState,
    Surroundings,
    decide,
)

TZ = ZoneInfo("Europe/Istanbul")
DAY = date(2026, 11, 23)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ).astimezone(UTC)


def frame(start: str = "09:00", end: str = "18:00", day: date = DAY, meal: bool = True) -> DayFrame:
    s, e = (time.fromisoformat(v) for v in (start, end))
    return build_frame(day, TZ, s, e, [("meal", time(12), time(13))] if meal else [])


SIGNAL = SignalState(
    name="focus.deadline_soon",
    data_class="personal",
    not_before=at(8),
    expires_at=at(0, day=DAY + timedelta(days=4)),
)
CARD = replace(SIGNAL, level1_at=at(8))  # carte montree lundi a 8 h
LATER = at(10, day=DAY + timedelta(days=1))  # mardi 10 h : 26 h plus tard, dans la plage


NO_FRAME = None
DEFAULT = "standard"


def around(
    f: DayFrame | str | None = DEFAULT, pushes: int = 0, devices: int = 1, day: date = DAY
) -> Surroundings:
    return Surroundings(
        frame=frame(day=day) if isinstance(f, str) else f,
        next_day_start=day_bounds(day + timedelta(days=1), TZ)[0],
        pushes_today=pushes,
        devices=devices,
    )


TUESDAY = DAY + timedelta(days=1)
WEDNESDAY = DAY + timedelta(days=2)


# ------------------------------------------------------------------- regles
def test_a_new_cause_first_becomes_a_card() -> None:
    assert decide(SIGNAL, around(), at(9)) == Decision("app", "new")


def test_a_card_shows_even_outside_working_hours_it_never_rings() -> None:
    night = replace(SIGNAL, not_before=at(2))
    assert decide(night, around(NO_FRAME), at(3)) == Decision("app", "new")
    assert decide(night, around(day_off(DAY)), at(3)) == Decision("app", "new")


def test_too_early_waits_until_not_before() -> None:
    assert decide(SIGNAL, around(), at(7)) == Decision("wait", "not_yet", at(8))


def test_an_expired_cause_expires() -> None:
    assert decide(CARD, around(), SIGNAL.expires_at).action == "expire"


def test_the_card_has_24_hours_to_be_seen() -> None:
    almost = at(8) + LEVEL1_IGNORED_AFTER - timedelta(minutes=1)
    assert decide(CARD, around(day=TUESDAY), almost) == Decision(
        "wait", "level1_pending", at(8) + LEVEL1_IGNORED_AFTER
    )
    assert decide(CARD, around(day=TUESDAY), LATER) == Decision("push", "ignored_24h")


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (replace(CARD, seen_at=at(9)), "seen"),
        (replace(CARD, closed_at=at(9)), "closed"),
        (replace(CARD, snoozed_until=at(12)), "postponed"),
        (replace(CARD, level2_done=True), "escalated"),
    ],
)
def test_no_escalation_once_the_user_reacted_or_after_one_notification(
    state: SignalState, reason: str
) -> None:
    assert decide(state, around(day=TUESDAY), LATER) == Decision("done", reason)


def test_nothing_sensitive_and_nothing_without_a_device() -> None:
    sensitive = replace(CARD, data_class="sensitive")
    assert decide(sensitive, around(day=TUESDAY), LATER) == Decision("done", "sensitive")
    assert decide(CARD, around(devices=0, day=TUESDAY), LATER) == Decision("done", "no_device")


@pytest.mark.parametrize(
    ("f", "now", "expected"),
    [
        # Sans cadre donne pour le jour : aucune heure supposee, on regarde plus tard.
        (None, LATER, Decision("wait", "no_frame", LATER + RECHECK)),
        (
            day_off(TUESDAY),
            LATER,
            Decision("wait", "day_off", day_bounds(DAY + timedelta(2), TZ)[0]),
        ),
        (
            frame("14:00", "23:00", TUESDAY, meal=False),
            LATER,
            Decision("wait", "before_work", at(14, day=TUESDAY)),
        ),
        (
            frame("08:00", "09:30", TUESDAY, meal=False),
            LATER,
            Decision("wait", "after_work", LATER + RECHECK),
        ),
        (frame(day=TUESDAY), at(12, 20, TUESDAY), Decision("wait", "break", at(13, day=TUESDAY))),
    ],
)
def test_quiet_hours_come_from_the_day_the_user_described(
    f: DayFrame | None, now: datetime, expected: Decision
) -> None:
    surroundings = around(day=TUESDAY)
    surroundings = Surroundings(f, surroundings.next_day_start, 0, 1)
    assert decide(CARD, surroundings, now) == expected


def test_the_end_of_the_working_range_is_already_quiet() -> None:
    f = frame("08:00", "10:00", TUESDAY, meal=False)
    assert decide(CARD, Surroundings(f, at(0, day=WEDNESDAY), 0, 1), at(10, day=TUESDAY)) == (
        Decision("wait", "after_work", at(10, 15, TUESDAY))
    )
    assert (
        decide(CARD, Surroundings(f, at(0, day=WEDNESDAY), 0, 1), at(9, 59, TUESDAY)).action
        == "push"
    )


def test_a_day_off_never_rings_even_with_hours() -> None:
    odd = DayFrame(TUESDAY, off=True, start=at(9, day=TUESDAY), end=at(18, day=TUESDAY))
    assert decide(CARD, Surroundings(odd, at(0, day=WEDNESDAY), 0, 1), LATER) == (
        Decision("wait", "day_off", at(0, day=WEDNESDAY))
    )


def test_a_night_shift_frame_allows_a_notification_after_midnight() -> None:
    night = frame("22:00", "04:00", DAY, meal=False)  # lundi 22 h -> mardi 4 h
    late = replace(CARD, level1_at=at(0, day=DAY))
    assert decide(late, Surroundings(night, at(0, day=TUESDAY), 0, 1), at(1, day=TUESDAY)) == (
        Decision("push", "ignored_24h")
    )


def test_three_notifications_a_day_at_most() -> None:
    full = around(pushes=DAILY_PUSH_BUDGET, day=TUESDAY)
    assert decide(CARD, full, LATER) == Decision("wait", "budget", full.next_day_start)
    assert decide(CARD, around(pushes=DAILY_PUSH_BUDGET - 1, day=TUESDAY), LATER).action == "push"


def test_never_wait_past_the_expiry() -> None:
    short = replace(CARD, expires_at=LATER + timedelta(minutes=5))
    decision = decide(short, around(pushes=DAILY_PUSH_BUDGET, day=TUESDAY), LATER)
    assert decision == Decision("wait", "budget", short.expires_at)


def test_a_test_notification_goes_now_outside_budget_and_quiet_hours() -> None:
    test = replace(SIGNAL, name=TEST_SIGNAL, not_before=at(3))
    assert decide(test, around(NO_FRAME, pushes=99), at(3)) == Decision("push", "test")
    assert decide(test, around(devices=0), at(3)) == Decision("done", "no_device")
    assert decide(replace(test, level2_done=True), around(), at(3)) == Decision("done", "tested")


# --------------------------------------------------------- semaines simulees
def _random_frame(rng: random.Random, day: date) -> DayFrame | None:
    roll = rng.random()
    if roll < 0.2:
        return None
    if roll < 0.3:
        return day_off(day)
    start = rng.randrange(0, 24 * 60, 15)
    length = rng.randrange(60, 16 * 60, 15)
    begin = time(start // 60, start % 60)
    finish_minutes = (start + length) % (24 * 60)
    return build_frame(day, TZ, begin, time(finish_minutes // 60, finish_minutes % 60))


def _within(f: DayFrame | None, now: datetime) -> bool:
    if f is None or f.off or f.start is None or f.end is None:
        return False
    return f.start <= now < f.end and not any(p.start <= now < p.end for p in f.breaks)


@pytest.mark.parametrize("seed", range(40))
def test_simulated_weeks_never_break_a_rule(seed: int) -> None:
    """Une semaine, minute par minute aux instants de decision, avec des cadres tires au
    hasard (sans cadre, jour off, nuits) et des causes nombreuses : jamais deux notifications
    pour une cause, jamais hors de la plage du jour, jamais plus de 3 par jour local, jamais
    avant 24 h de carte ignoree, jamais pour une cause expiree."""
    rng = random.Random(seed)  # noqa: S311 (tirage de test reproductible)
    start = at(0)
    frames = {
        DAY + timedelta(days=d): _random_frame(rng, DAY + timedelta(days=d)) for d in range(8)
    }
    states = [
        replace(
            SIGNAL,
            not_before=start + timedelta(minutes=rng.randrange(0, 4 * 24 * 60)),
            expires_at=start + timedelta(minutes=rng.randrange(5 * 24 * 60, 8 * 24 * 60)),
            data_class=rng.choice(["personal", "personal", "sensitive"]),
        )
        for _ in range(12)
    ]
    seen_by_user = {i for i in range(len(states)) if rng.random() < 0.3}
    pushes: dict[date, int] = {}
    sent: list[int] = []
    next_check = [s.not_before for s in states]
    done = [False] * len(states)
    now = start
    end = start + timedelta(days=7)
    while now < end:
        today = now.astimezone(TZ).date()
        for i, state in enumerate(states):
            if done[i] or now < next_check[i]:
                continue
            surroundings = Surroundings(
                frames[today], day_bounds(today + timedelta(days=1), TZ)[0], pushes.get(today, 0), 1
            )
            decision = decide(state, surroundings, now)
            if decision.action == "app":
                states[i] = state = replace(state, level1_at=now)
                if i in seen_by_user:
                    states[i] = state = replace(state, seen_at=now + timedelta(hours=1))
                next_check[i] = now
            elif decision.action == "push":
                assert state.level1_at is not None
                assert now >= state.level1_at + LEVEL1_IGNORED_AFTER
                assert now < state.expires_at and state.data_class != "sensitive"
                assert state.seen_at is None and not state.level2_done
                assert _within(frames[today], now), (now, frames[today])
                pushes[today] = pushes.get(today, 0) + 1
                assert pushes[today] <= DAILY_PUSH_BUDGET
                states[i] = replace(state, level2_done=True)
                sent.append(i)
                next_check[i] = now
            elif decision.action == "wait":
                assert decision.next_check is not None and decision.next_check > now
                assert decision.next_check <= state.expires_at
                next_check[i] = decision.next_check
            else:
                done[i] = True
        now += timedelta(minutes=5)
    assert len(sent) == len(set(sent))
