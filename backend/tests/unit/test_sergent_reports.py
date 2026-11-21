"""Rapports du Sergent (PR 50) : des regles, chaque fait avec sa source, une seule question.

Reperes : mercredi 18 novembre 2026 a Ankara (UTC+3), comme les tests du planificateur dont
on reprend les aides. La vue du jour est construite sans base : plan_day est pur.
"""

import dataclasses
from datetime import date, datetime, timedelta

from test_planner import DAY, all_day, at, event, frame, task

from lorakus.core.agents.contract import MAX_REPORT_CHARS, SpecialistReport
from lorakus.core.planning.days import DayFrame, day_off
from lorakus.core.planning.planner import plan_day
from lorakus.core.planning.service import AgendaView, TaskView
from lorakus.core.planning.today import TodayView, upcoming_tasks
from lorakus_modules.focus.reports import (
    FRAME_SOURCE,
    PLAN_SOURCE,
    day_report,
    deadlines_report,
    task_source,
)

NOW = at(13, 0)


def view(
    tasks: list[TaskView],
    agenda: list[AgendaView] | None = None,
    day_frame: DayFrame | None = None,
    now: datetime = NOW,
) -> TodayView:
    agenda = agenda or []
    return TodayView(
        day=DAY,
        timezone="Europe/Istanbul",
        now=now,
        agenda=tuple(agenda),
        plan=plan_day(now, day_frame, agenda, tasks),
        tasks={str(t.id): t for t in tasks},
        overdue=tuple(t for t in tasks if t.due_on is not None and t.due_on < DAY),
        upcoming=upcoming_tasks(tasks, DAY),
    )


def facts(report: SpecialistReport) -> list[tuple[str, str, str, bool]]:
    return [(f.label, f.value, f.source, f.measured) for f in report.facts]


def academic(title: str, due: date | None, minutes: int | None = None) -> TaskView:
    return dataclasses.replace(
        task(title, due=due, minutes=minutes), owner_module="academic", owner_ref="x"
    )


TP = academic("Machine Learning : TP 2", date(2026, 11, 20), 180)
LATE = task("Rapport de stage", due=date(2026, 11, 16), minutes=60)
DM = task("DM d'algo", due=date(2026, 11, 19), minutes=None)  # sans duree


# ------------------------------------------------------------ journee
def test_without_a_frame_nothing_is_placed_and_the_one_question_is_when() -> None:
    report = day_report(view([TP, LATE, DM], [event((15, 0), (17, 0), "CENG 499")]))
    assert report.status == "ok"
    assert report.summary == (
        "Tu n'as pas dit quand tu travailles aujourd'hui : aucun créneau n'est placé. "
        "Tâches : 1 en retard, 1 sans durée."
    )
    assert report.clarification == "Quand comptes-tu travailler aujourd'hui ?"
    assert facts(report) == [
        (
            "En retard",
            "Rapport de stage, pour le lundi 16 novembre 2026 (il y a 2 jours)",
            "Tâche « Rapport de stage »",
            True,
        ),
        ("15:00 - 17:00", "CENG 499", "Agenda (calendrier importé)", True),
        (
            "Durée inconnue",
            "DM d'algo, pour le jeudi 19 novembre 2026 (demain)",
            "Tâche « DM d'algo »",
            True,
        ),
    ]
    assert report.confidence is not None and report.confidence.level == 1.0


def test_only_three_late_tasks_are_detailed() -> None:
    late = [task(f"Retard {n}", due=date(2026, 11, 10 + n), minutes=30) for n in range(4)]
    report = day_report(view(late))
    assert [f.value.split(",")[0] for f in report.facts] == ["Retard 0", "Retard 1", "Retard 2"]
    assert report.summary.endswith("Tâches : 4 en retard.")


def test_without_a_frame_tasks_without_duration_are_still_work_to_place() -> None:
    report = day_report(view([DM]))
    assert report.clarification == "Quand comptes-tu travailler aujourd'hui ?"


def test_nothing_to_do_and_no_frame_asks_nothing() -> None:
    report = day_report(view([]))
    assert report.clarification is None
    assert report.facts == []
    assert report.summary.startswith("Tu n'as pas dit quand tu travailles aujourd'hui")


def test_the_plan_comes_with_hours_sources_and_what_is_estimated() -> None:
    day = frame((14, 0), (22, 0), breaks=(((19, 0), (19, 45)),))
    agenda = [event((15, 0), (16, 0), "CENG 499"), all_day("Anniversaire")]
    report = day_report(view([TP, LATE], agenda, day))

    assert report.status == "ok"
    assert report.summary == "Plan proposé : 4 h de travail. Tâches : 1 en retard."
    assert report.clarification is None  # tout a une duree : rien a demander
    assert facts(report) == [
        ("Ta journée", "travail de 14:00 à 22:00, pauses : 19:00 - 19:45", FRAME_SOURCE, True),
        (
            "En retard",
            "Rapport de stage, pour le lundi 16 novembre 2026 (il y a 2 jours)",
            "Tâche « Rapport de stage »",
            True,
        ),
        ("14:00 - 15:00", "travailler sur Rapport de stage", PLAN_SOURCE, False),
        ("15:00 - 16:00", "CENG 499", "Agenda (calendrier importé)", True),
        ("16:00 - 18:00", "travailler sur Machine Learning : TP 2", PLAN_SOURCE, False),
        ("18:15 - 19:00", "travailler sur Machine Learning : TP 2", PLAN_SOURCE, False),
        ("19:45 - 20:00", "travailler sur Machine Learning : TP 2", PLAN_SOURCE, False),
    ]


def test_with_a_frame_the_question_is_the_duration_of_the_most_urgent_task() -> None:
    later = task("Lecture", due=date(2026, 11, 24), minutes=None)
    report = day_report(view([later, DM, TP], day_frame=frame((14, 0), (22, 0))))
    assert report.clarification == "Combien de temps te prendra « DM d'algo » ?"
    assert report.summary == "Plan proposé : 3 h de travail. Tâches : 2 sans durée."
    unknown = [f for f in facts(report) if f[0] == "Durée inconnue"]
    assert [source for _, _, source, _ in unknown] == ["Tâche « DM d'algo »", "Tâche « Lecture »"]


def test_a_night_frame_says_when_hours_are_the_next_day() -> None:
    night = frame((21, 0), (2, 0))
    report = day_report(view([TP], day_frame=night, now=at(21, 0)))
    assert report.facts[0].value == "travail de 21:00 à 02:00 (le lendemain)"
    assert [f.label for f in report.facts[1:]] == [
        "21:00 - 23:00",
        "23:15 - 00:15 (le lendemain)",
    ]


def test_a_day_off_and_a_finished_frame_ask_nothing() -> None:
    off = day_report(view([TP, DM], day_frame=day_off(DAY)))
    assert off.summary == "Jour sans travail : rien n'est proposé. Tâches : 1 sans durée."
    assert facts(off)[0] == ("Ta journée", "pas de travail aujourd'hui", FRAME_SOURCE, True)
    assert off.clarification is None
    over = day_report(view([TP, DM], day_frame=frame((8, 0), (12, 0))))  # il est 13 h
    assert over.summary == "Ta plage de travail d'aujourd'hui est finie. Tâches : 1 sans durée."
    assert over.clarification is None


def test_what_does_not_fit_is_counted_in_the_summary() -> None:
    big = task("Projet", due=date(2026, 11, 20), minutes=600)
    report = day_report(view([big], day_frame=frame((14, 0), (18, 0))))
    assert report.summary == (
        "Plan proposé : 3 h 45 de travail. Tâches : 6 h 15 sans place aujourd'hui."
    )


def test_an_empty_frame_says_there_is_nothing_to_place() -> None:
    report = day_report(view([], day_frame=frame((14, 0), (22, 0))))
    assert report.summary == "Rien à placer dans ta plage de travail."
    assert report.clarification is None


def test_a_crowded_day_is_cut_to_fit_and_says_so() -> None:
    tasks = [
        task(f"Tâche au titre assez long pour remplir le rapport numéro {n}", minutes=30)
        for n in range(12)
    ]
    agenda = [
        event((h, 0), (h, 30), f"Cours numéro {h} dans un amphithéâtre") for h in range(14, 20)
    ]
    crowded = view(tasks, agenda, frame((13, 0), (23, 0)))
    report = day_report(crowded)
    assert report.status == "partial"
    assert len(report.model_dump_json()) <= MAX_REPORT_CHARS
    dropped = 1 + len(crowded.plan.blocks) + len(agenda) - len(report.facts)
    assert dropped > 0
    assert report.summary.endswith(f"{dropped} autres éléments non détaillés.")
    # Les premiers faits sont gardes, dans l'ordre : le cadre d'abord.
    assert report.facts[0].label == "Ta journée"


def test_one_dropped_fact_is_singular() -> None:
    from lorakus_modules.focus import reports

    assert reports._more(1) == " 1 autre élément non détaillé."
    assert reports._more(0) == ""


def test_long_titles_are_cut_and_module_tasks_say_where_they_come_from() -> None:
    long = academic("Un intitulé de devoir vraiment très long " * 5, DAY + timedelta(days=1))
    assert task_source(long).startswith("Cours « Un intitulé")
    assert len(task_source(long)) <= 120
    report = day_report(view([long]))
    [fact] = report.facts
    assert fact.value.endswith("…") and len(fact.value) <= 200


# ----------------------------------------------------------- echeances
def test_deadlines_list_what_is_late_then_the_week() -> None:
    far = task("Plus tard", due=DAY + timedelta(days=9), minutes=30)
    report = deadlines_report(view([far, DM, TP, LATE]))
    assert report.summary == "2 échéances d'ici une semaine, 1 en retard."
    assert facts(report) == [
        (
            "En retard",
            "Rapport de stage, pour le lundi 16 novembre 2026 (il y a 2 jours)",
            "Tâche « Rapport de stage »",
            True,
        ),
        (
            "Échéance",
            "DM d'algo, pour le jeudi 19 novembre 2026 (demain), durée inconnue",
            "Tâche « DM d'algo »",
            True,
        ),
        (
            "Échéance",
            "Machine Learning : TP 2, pour le vendredi 20 novembre 2026 (dans 2 jours), "
            "durée estimée 3 h",
            "Cours « Machine Learning : TP 2 »",
            True,
        ),
    ]
    assert report.clarification is None


def test_no_deadline_is_said_plainly() -> None:
    report = deadlines_report(view([task("Sans date", due=None)]))
    assert report.summary == "Aucune échéance d'ici une semaine, et rien en retard."
    assert report.facts == []
    only_late = deadlines_report(view([LATE]))
    assert only_late.summary == "0 échéance d'ici une semaine, 1 en retard."
    one = deadlines_report(view([DM]))
    assert one.summary == "1 échéance d'ici une semaine, 0 en retard."


def test_many_deadlines_are_cut_to_fit() -> None:
    tasks = [
        task(f"Devoir au titre plutôt long numéro {n}", due=DAY + timedelta(days=n % 7), minutes=60)
        for n in range(15)
    ]
    report = deadlines_report(view(tasks))
    assert report.status == "partial"
    assert report.summary.startswith("15 échéances d'ici une semaine, 0 en retard.")
    assert report.summary.endswith("autres éléments non détaillés.")
    assert len(report.model_dump_json()) <= MAX_REPORT_CHARS


def test_reports_use_the_account_timezone() -> None:
    paris = dataclasses.replace(
        view([TP], day_frame=frame((14, 0), (22, 0))), timezone="Europe/Paris"
    )
    report = day_report(paris)
    # 14:00 a Ankara = 12:00 a Paris
    assert report.facts[0].value.startswith("travail de 12:00 à 20:00")
