"""Temps de l'utilisateur (PR 44, ADR 0018) : fuseau, « aujourd'hui », bornes d'un jour.

Horloges fixes partout : un test qui depend de l'heure reelle finit par echouer a minuit
(lecon de la PR 41).
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lorakus.core.account.clock import (
    InvalidTimezoneError,
    day_bounds,
    local_today,
    parse_timezone,
)
from lorakus.core.account.dates import duration, french_date, relative_day

PARIS = ZoneInfo("Europe/Paris")
ISTANBUL = ZoneInfo("Europe/Istanbul")


@pytest.mark.parametrize(
    "name", ["Europe/Paris", "Europe/Istanbul", "America/Argentina/Salta", "UTC"]
)
def test_known_timezones_are_accepted(name: str) -> None:
    assert parse_timezone(name).key == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Mars/Olympus",
        "../../etc/passwd",
        "/etc/localtime",
        "Europe/../Paris",
        "Europe/Paris\n",
        "Europe/Paris; DROP TABLE",
        "A" * 65,
    ],
)
def test_unknown_or_malformed_timezones_are_refused(name: str) -> None:
    with pytest.raises(InvalidTimezoneError):
        parse_timezone(name)


def test_today_depends_on_the_users_timezone_around_midnight() -> None:
    # 22:30 UTC : 23:30 a Paris, mais deja 01:30 le lendemain a Ankara.
    now = datetime(2026, 11, 18, 22, 30, tzinfo=UTC)
    assert local_today(now, PARIS) == date(2026, 11, 18)
    assert local_today(now, ISTANBUL) == date(2026, 11, 19)


def test_a_day_is_24_hours_most_of_the_time() -> None:
    start, end = day_bounds(date(2026, 11, 18), PARIS)
    assert start == datetime(2026, 11, 17, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=24)


def test_days_of_the_clock_changes_last_23_and_25_hours_in_paris() -> None:
    spring = day_bounds(date(2026, 3, 29), PARIS)
    autumn = day_bounds(date(2026, 10, 25), PARIS)
    assert spring[1] - spring[0] == timedelta(hours=23)
    assert autumn[1] - autumn[0] == timedelta(hours=25)
    # Ankara n'a pas de changement d'heure.
    turkish = day_bounds(date(2026, 3, 29), ISTANBUL)
    assert turkish[1] - turkish[0] == timedelta(hours=24)


def test_consecutive_days_touch_exactly() -> None:
    for offset in range(370):
        day = date(2026, 1, 1) + timedelta(days=offset)
        assert day_bounds(day, PARIS)[1] == day_bounds(day + timedelta(days=1), PARIS)[0]


def test_dates_are_written_in_french_without_the_server_locale() -> None:
    assert french_date(date(2026, 11, 20)) == "vendredi 20 novembre 2026"
    assert french_date(date(2027, 8, 1)) == "dimanche 1 août 2027"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(0, "aujourd'hui"), (1, "demain"), (-1, "hier"), (2, "dans 2 jours"), (-3, "il y a 3 jours")],
)
def test_relative_days(offset: int, expected: str) -> None:
    today = date(2026, 11, 18)
    assert relative_day(today + timedelta(days=offset), today) == expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(45, "45 min"), (60, "1 h"), (180, "3 h"), (90, "1 h 30"), (125, "2 h 05")],
)
def test_durations(minutes: int, expected: str) -> None:
    assert duration(minutes) == expected
