"""Cadre du jour (PR 49) : construction, bornes, texte et lecture tolerante, sans base.

Reperes : samedi 21 novembre 2026 a Paris (UTC+1). Les horaires de l'utilisateur changent
tous les jours : le cadre ne vaut que pour un jour, et peut passer minuit.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from lorakus.core.planning import days
from lorakus.core.planning.days import (
    DayFrame,
    InvalidFrameError,
    Pause,
    build_frame,
    check_not_over,
    day_off,
    frame_lines,
    read_row,
)
from lorakus.core.planning.models import PlanningDay

PARIS = ZoneInfo("Europe/Paris")
DAY = date(2026, 11, 21)
NEXT = DAY + timedelta(days=1)


def at(hour: int, minute: int = 0, day: date = DAY, tz: ZoneInfo = PARIS) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(UTC)


def t(text: str) -> time:
    return time.fromisoformat(text)


def build(start: str, end: str, *breaks: tuple[str, str, str], day: date = DAY) -> DayFrame:
    return build_frame(day, PARIS, t(start), t(end), [(k, t(a), t(b)) for k, a, b in breaks])  # type: ignore[misc]


# ------------------------------------------------------------- construire
def test_a_frame_is_built_in_the_account_timezone() -> None:
    frame = build("15:00", "23:00", ("meal", "19:30", "20:15"))
    assert frame == DayFrame(
        DAY, False, at(15, 0), at(23, 0), (Pause("meal", at(19, 30), at(20, 15)),)
    )


def test_an_end_earlier_than_the_start_falls_the_next_day() -> None:
    night = build("22:00", "04:00", ("meal", "23:30", "00:15"), ("break", "02:00", "02:20"))
    assert (night.start, night.end) == (at(22, 0), at(4, 0, NEXT))
    assert [(p.start, p.end) for p in night.breaks] == [
        (at(23, 30), at(0, 15, NEXT)),  # le repas passe minuit
        (at(2, 0, NEXT), at(2, 20, NEXT)),  # la pause tombe le lendemain
    ]


def test_breaks_come_back_sorted() -> None:
    frame = build("08:00", "23:00", ("sport", "18:00", "19:00"), ("meal", "12:00", "13:00"))
    assert [p.kind for p in frame.breaks] == ["meal", "sport"]


@pytest.mark.parametrize(
    ("start", "end"),
    [("10:00", "10:29"), ("10:00", "10:00"), ("08:00", "04:01"), ("10:00", "06:01")],
)
def test_a_frame_lasts_from_thirty_minutes_to_twenty_hours(start: str, end: str) -> None:
    with pytest.raises(InvalidFrameError, match="30 minutes à 20 heures"):
        build(start, end)


def test_the_frame_limits_are_inclusive() -> None:
    assert build("10:00", "10:30").end == at(10, 30)
    assert build("08:00", "04:00").end == at(4, 0, NEXT)  # 20 heures pile


@pytest.mark.parametrize(
    "pause",
    [
        ("meal", "12:00", "12:09"),  # trop courte
        ("meal", "12:00", "16:01"),  # trop longue
        ("meal", "12:00", "12:00"),  # vide
    ],
)
def test_a_break_lasts_from_ten_minutes_to_four_hours(pause: tuple[str, str, str]) -> None:
    with pytest.raises(InvalidFrameError, match="10 minutes à 4 heures"):
        build("08:00", "23:00", pause)


def test_break_limits_are_inclusive() -> None:
    frame = build("08:00", "23:00", ("meal", "12:00", "12:10"), ("sport", "17:00", "21:00"))
    assert [p.end - p.start for p in frame.breaks] == [timedelta(minutes=10), timedelta(hours=4)]


@pytest.mark.parametrize(
    "pause",
    [
        ("meal", "07:00", "07:30"),  # avant la plage
        ("meal", "22:45", "23:30"),  # deborde a la fin
        ("meal", "23:00", "23:30"),  # commence quand elle finit
    ],
)
def test_a_break_must_be_inside_the_frame(pause: tuple[str, str, str]) -> None:
    with pytest.raises(InvalidFrameError, match="n'est pas dans la plage"):
        build("08:00", "23:00", pause)


def test_a_break_may_touch_both_ends_of_the_frame() -> None:
    frame = build("08:00", "23:00", ("meal", "08:00", "08:30"), ("break", "22:30", "23:00"))
    assert len(frame.breaks) == 2


def test_no_more_than_six_breaks() -> None:
    six = [("break", f"{h:02d}:00", f"{h:02d}:15") for h in range(9, 15)]
    assert len(build("08:00", "23:00", *six).breaks) == 6
    with pytest.raises(InvalidFrameError, match="6 pauses"):
        build("08:00", "23:00", *six, ("break", "16:00", "16:15"))


def test_a_frame_follows_wall_clock_time_on_clock_change_days() -> None:
    autumn = date(2026, 10, 25)  # Paris : 25 heures ce jour-la, changement a 3 h
    night = build("22:00", "06:00", day=autumn - timedelta(days=1))
    assert night.start is not None and night.end is not None
    assert night.end - night.start == timedelta(hours=9)  # une heure de plus cette nuit-la
    assert night.end.astimezone(PARIS).strftime("%H:%M") == "06:00"


def test_a_frame_already_over_is_refused() -> None:
    frame = build("08:00", "12:00")
    check_not_over(frame, at(11, 59))
    with pytest.raises(InvalidFrameError, match="déjà passée"):
        check_not_over(frame, at(12, 0))
    check_not_over(day_off(DAY), at(23, 0))  # un jour sans travail n'a pas de fin


# ------------------------------------------------------------------ texte
def test_the_frame_reads_in_french() -> None:
    night = build("15:00", "03:30", ("meal", "22:00", "22:45"), ("sport", "18:00", "19:00"))
    assert frame_lines(night, PARIS) == [
        "Travail : de 15 h à 3 h 30 (le lendemain) (12 h 30)",
        "Sport : de 18 h à 19 h",
        "Repas : de 22 h à 22 h 45",
    ]
    assert frame_lines(build("09:00", "12:00"), PARIS) == ["Travail : de 9 h à 12 h (3 h)"]
    assert frame_lines(day_off(DAY), PARIS) == ["Pas de travail ce jour-là"]


# ------------------------------------------------------- lecture tolerante
def row(**changes: Any) -> PlanningDay:
    frame = build("10:00", "22:00", ("meal", "13:00", "14:00"))
    fields: dict[str, Any] = {
        "user_id": uuid.uuid4(),
        "day": DAY,
        "off": False,
        "starts_at": frame.start,
        "ends_at": frame.end,
        "breaks": days._breaks_json(frame),
        "source_kind": "user",
    }
    fields.update(changes)
    return PlanningDay(**fields)


def test_a_stored_frame_reads_back_the_same() -> None:
    assert read_row(row()) == build("10:00", "22:00", ("meal", "13:00", "14:00"))
    assert read_row(row(off=True, starts_at=None, ends_at=None, breaks=[])) == day_off(DAY)


@pytest.mark.parametrize(
    "changes",
    [
        {"starts_at": None},
        {"ends_at": at(10, 29)},  # trop courte
        {"ends_at": at(6, 1, NEXT)},  # trop longue
        {"breaks": "pas un tableau"},
        # sept pauses lisibles : une de trop
        {
            "breaks": [
                {
                    "kind": "break",
                    "start": f"2026-11-21T{h}:00:00+00:00",
                    "end": f"2026-11-21T{h}:15:00+00:00",
                }
                for h in range(10, 17)
            ]
        },
        # vide
        {
            "breaks": [
                {
                    "kind": "meal",
                    "start": "2026-11-21T12:00:00+00:00",
                    "end": "2026-11-21T12:00:00+00:00",
                }
            ]
        },
        {"breaks": ["texte"]},
        {
            "breaks": [
                {
                    "kind": "sieste",
                    "start": "2026-11-21T12:00:00+00:00",
                    "end": "2026-11-21T13:00:00+00:00",
                }
            ]
        },
        {
            "breaks": [
                {"kind": "meal", "start": "2026-11-21T12:00:00", "end": "2026-11-21T13:00:00"}
            ]
        },
        {"breaks": [{"kind": "meal", "start": 12, "end": 13}]},
        {"breaks": [{"kind": "meal", "start": "pas une date", "end": "2026-11-21T13:00:00+00:00"}]},
        # hors de la plage, ou a l'envers
        {
            "breaks": [
                {
                    "kind": "meal",
                    "start": "2026-11-21T08:00:00+00:00",
                    "end": "2026-11-21T09:30:00+00:00",
                }
            ]
        },
        {
            "breaks": [
                {
                    "kind": "meal",
                    "start": "2026-11-21T13:00:00+00:00",
                    "end": "2026-11-21T12:00:00+00:00",
                }
            ]
        },
    ],
)
def test_an_unreadable_row_counts_as_no_frame(changes: dict[str, Any]) -> None:
    assert read_row(row(**changes)) is None
