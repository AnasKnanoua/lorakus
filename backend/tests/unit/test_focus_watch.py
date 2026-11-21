"""Regle des echeances du Sergent (P5) : le signal d'une tache, ecrit par le code."""

import uuid
from datetime import UTC, date, datetime

from lorakus.core.planning.service import TaskView
from lorakus_modules.focus.watch import RULE, SIGNAL, draft, key, started

TODAY = date(2026, 11, 23)
NOW = datetime(2026, 11, 23, 5, tzinfo=UTC)
END = datetime(2026, 11, 26, 21, tzinfo=UTC)


def task(**changes: object) -> TaskView:
    values: dict[str, object] = {
        "id": uuid.UUID(int=1),
        "title": "CSEC507 : rapport",
        "notes": None,
        "status": "open",
        "priority": 2,
        "due_on": date(2026, 11, 26),
        "estimate_minutes": 90,
        "parent_id": None,
        "owner_module": "academic",
        "owner_ref": "a1",
        "source_kind": "user",
        "created_at": NOW,
        "completed_at": None,
        "estimate_source": "user",
    }
    values.update(changes)
    return TaskView(**values)  # type: ignore[arg-type]


def test_the_signal_says_when_with_the_absolute_date() -> None:
    signal = draft(task(), date(2026, 11, 26), TODAY, NOW, END)
    assert signal.name == SIGNAL and signal.kind == "scheduled" and signal.data_class == "personal"
    assert signal.title == "À rendre dans 3 jours"
    assert signal.body == "CSEC507 : rapport · jeudi 26 novembre 2026. Pas encore commencé."
    assert signal.firm_body == (
        "Toujours pas commencé : « CSEC507 : rapport » est à rendre dans 3 jours (jeudi 26 "
        "novembre 2026). Il te faut environ 1 h 30. Ouvre Ma journée pour lui trouver un créneau."
    )
    assert signal.rule == RULE and signal.url == "/today"
    assert (signal.not_before, signal.expires_at) == (NOW, END)
    assert signal.subject_ref == f"task:{uuid.UUID(int=1)}"
    assert (
        signal.dedup_key
        == key(task(), date(2026, 11, 26))
        == f"{SIGNAL}:{uuid.UUID(int=1)}:2026-11-26"
    )
    assert [(f.label, f.source, f.measured) for f in signal.facts] == [
        ("Tâche", "Cours", True),
        ("Échéance", "Cours", True),
        ("Avancement", "Planning", True),
        ("Durée estimée", "Planning", True),
    ]


def test_a_closer_deadline_is_stronger() -> None:
    strengths = [draft(task(), date(2026, 11, 23 + d), TODAY, NOW, END).strength for d in range(4)]
    assert strengths == [1.0, 0.75, 0.5, 0.25]
    assert draft(task(), date(2026, 11, 24), TODAY, NOW, END).title == "À rendre demain"
    assert draft(task(), TODAY, TODAY, NOW, END).title == "À rendre aujourd'hui"


def test_an_estimate_by_lorakus_is_shown_as_estimated() -> None:
    signal = draft(task(estimate_source="assistant"), date(2026, 11, 26), TODAY, NOW, END)
    assert signal.facts[3].measured is False
    unknown = draft(
        task(estimate_minutes=None, estimate_source=None), date(2026, 11, 26), TODAY, NOW, END
    )
    assert unknown.facts[3].value == "inconnue"
    assert unknown.firm_body is not None and "Il te faut" not in unknown.firm_body
    personal = draft(task(owner_module=None), date(2026, 11, 26), TODAY, NOW, END)
    assert personal.facts[0].source == "Tâches"


def test_a_task_is_started_once_a_step_is_done() -> None:
    assert not started(task())
    assert not started(task(subtasks=3, open_subtasks=3))
    assert started(task(subtasks=3, open_subtasks=2))
