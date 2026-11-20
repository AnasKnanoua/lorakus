"""Catalogue des preferences de planification (PR 48) : valeurs typees, bornes, texte."""

from datetime import time
from typing import Any

import pytest

from lorakus.core.planning.preferences import (
    DEFAULTS,
    KEYS,
    LABEL,
    InvalidPreferenceError,
    Key,
    PlanningPrefs,
    TimeRange,
    check_together,
    current_value,
    parse_value,
    to_json,
    value_text,
)


def test_the_catalogue_is_closed_and_every_key_has_a_label_and_a_default() -> None:
    assert KEYS == ("work_start", "work_end", "lunch", "dinner", "rest_days", "daily_cap")
    assert set(LABEL) == set(KEYS)
    assert [current_value(DEFAULTS, key) for key in KEYS] == [
        time(8, 0),
        time(22, 0),
        None,
        None,
        frozenset(),
        360,
    ]


@pytest.mark.parametrize(
    ("key", "raw", "value", "text"),
    [
        ("work_start", {"time": "07:30"}, time(7, 30), "7 h 30"),
        ("work_end", {"time": "21:00"}, time(21, 0), "21 h"),
        ("work_start", {"time": "00:00"}, time(0, 0), "0 h"),
        ("work_end", {"time": "23:59"}, time(23, 59), "23 h 59"),
        (
            "lunch",
            {"start": "12:30", "end": "13:30"},
            TimeRange(time(12, 30), time(13, 30)),
            "de 12 h 30 à 13 h 30",
        ),
        (
            "dinner",
            {"start": "19:00", "end": "19:15"},
            TimeRange(time(19, 0), time(19, 15)),
            "de 19 h à 19 h 15",
        ),
        (
            "lunch",
            {"start": "11:00", "end": "14:00"},
            TimeRange(time(11, 0), time(14, 0)),
            "de 11 h à 14 h",
        ),
        ("rest_days", {"days": [6, 5, 6]}, frozenset({5, 6}), "samedi, dimanche"),
        ("rest_days", {"days": [0]}, frozenset({0}), "lundi"),
        (
            "rest_days",
            {"days": [0, 1, 2, 3, 4, 5]},
            frozenset(range(6)),
            "lundi, mardi, mercredi, jeudi, vendredi, samedi",
        ),
        ("daily_cap", {"minutes": 30}, 30, "30 min au plus"),
        ("daily_cap", {"minutes": 720}, 720, "12 h au plus"),
        ("daily_cap", {"minutes": 270}, 270, "4 h 30 au plus"),
    ],
)
def test_valid_values_are_typed_written_and_read_back(
    key: Key, raw: dict[str, Any], value: object, text: str
) -> None:
    parsed = parse_value(key, raw)
    assert parsed == value
    assert value_text(key, parsed) == text
    assert parse_value(key, to_json(key, parsed)) == parsed  # aller-retour par la base


@pytest.mark.parametrize(
    ("key", "raw", "message"),
    [
        ("work_start", {}, "HH:MM"),
        ("work_start", {"time": None}, "HH:MM"),
        ("work_start", {"time": 8}, "HH:MM"),
        ("work_start", {"time": "8:00"}, "HH:MM"),
        ("work_start", {"time": "24:00"}, "HH:MM"),
        ("work_start", {"time": "08:00:30"}, "HH:MM"),
        ("work_start", {"time": "08:00+02:00"}, "HH:MM"),
        ("work_end", {"time": "soir"}, "HH:MM"),
        ("lunch", {"start": "12:00"}, "HH:MM"),
        ("lunch", {"start": "13:00", "end": "12:00"}, "repas"),
        ("lunch", {"start": "12:00", "end": "12:00"}, "repas"),
        ("lunch", {"start": "12:00", "end": "12:14"}, "repas"),
        ("dinner", {"start": "18:00", "end": "21:01"}, "repas"),
        ("rest_days", {}, "au moins un jour"),
        ("rest_days", {"days": []}, "au moins un jour"),
        ("rest_days", {"days": "dimanche"}, "au moins un jour"),
        ("rest_days", {"days": [7]}, "au moins un jour"),
        ("rest_days", {"days": [-1]}, "au moins un jour"),
        ("rest_days", {"days": [True]}, "au moins un jour"),
        ("rest_days", {"days": ["6"]}, "au moins un jour"),
        ("rest_days", {"days": [0, 1, 2, 3, 4, 5, 6]}, "au moins un jour de travail"),
        ("daily_cap", {}, "minutes"),
        ("daily_cap", {"minutes": "240"}, "minutes"),
        ("daily_cap", {"minutes": True}, "minutes"),
        ("daily_cap", {"minutes": 29}, "Entre 30 minutes"),
        ("daily_cap", {"minutes": 721}, "Entre 30 minutes"),
    ],
)
def test_values_outside_the_catalogue_are_refused(
    key: Key, raw: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidPreferenceError, match=message):
        parse_value(key, raw)


def test_the_working_day_must_last_an_hour() -> None:
    check_together(PlanningPrefs(work_start=time(9, 0), work_end=time(10, 0)))
    for start, end in (
        (time(9, 0), time(9, 59)),
        (time(22, 0), time(8, 0)),
        (time(9, 0), time(9, 0)),
    ):
        with pytest.raises(InvalidPreferenceError, match="au moins une heure"):
            check_together(PlanningPrefs(work_start=start, work_end=end))


def test_absent_values_have_a_text_too() -> None:
    assert [value_text(key, current_value(DEFAULTS, key)) for key in KEYS] == [
        "8 h",
        "22 h",
        "aucun",
        "aucun",
        "aucun",
        "6 h au plus",
    ]
