"""Rapports du Sergent (PR 50) : des regles, aucun LLM, chaque fait avec sa source.

Deux rapports, calcules a partir de la vue du jour du Core (planning/today.py), donc du
meme plan que la page « Ma journee » :

- `day_plan` : la journee en cours. Le cadre donne par l'utilisateur (ou son absence), le
  plan propose heure par heure, les cours, les retards, ce qui reste a estimer.
- `deadlines` : les retards et les echeances des sept prochains jours.

Chaque fait dit d'ou il vient (« Agenda », « Tâche », « Cours » pour une tache du module
academic, « Plan calculé par Lorakus ») et s'il est mesure (une echeance, un creneau de
l'agenda) ou estime (un creneau propose, une duree). Le rapport tient en 1 500 caracteres
(contrat, ADR 0026) : les faits sont ajoutes par ordre d'importance tant qu'il y a la place,
et le rapport devient « partiel » s'il en manque.

Au plus UNE question, et seulement si la reponse change le plan : sans cadre du jour, rien
ne peut etre place (« quand travailles-tu aujourd'hui ? ») ; sinon, une tache a faire
bientot sans duree n'est pas placee (« combien de temps te prendra … ? »). Aucune reponse par
defaut : le planificateur ne suppose ni heure ni duree (PR 49), le Sergent non plus.
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.agents.contract import Confidence, Fact, SpecialistReport
from lorakus.core.planning.service import AgendaView, TaskView
from lorakus.core.planning.today import TodayView

PLAN_SOURCE: Final = "Plan calculé par Lorakus (règles)"
FRAME_SOURCE: Final = "Ta journée, telle que tu l'as dite"
CONFIDENCE: Final = Confidence(
    level=1.0,
    reason="Calculé par des règles à partir de tes tâches, de ton agenda et de ta journée.",
)
_TITLE: Final = 70  # un titre trop long est coupe : le rapport doit tenir


def _short(text: str, limit: int = _TITLE) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _hour(moment: datetime, tz: ZoneInfo, day: date) -> str:
    local = moment.astimezone(tz)
    return f"{local:%H:%M}" + (" (le lendemain)" if local.date() > day else "")


def task_source(task: TaskView) -> str:
    """D'ou vient une tache : le module qui l'a creee, ou la liste des taches."""
    kind = "Cours" if task.owner_module == "academic" else "Tâche"
    return f"{kind} « {_short(task.title, 90)} »"


def _due(task: TaskView, today: date) -> str:
    if task.due_on is None:
        return "sans échéance"
    return f"pour le {french_date(task.due_on)} ({relative_day(task.due_on, today)})"


def _fit(
    summary: Callable[[int], str],
    facts: Sequence[Fact],
    clarification: str | None,
    freshness: datetime,
) -> SpecialistReport:
    """Le rapport le plus complet qui respecte le contrat : les faits sont pris dans l'ordre
    (le plus important d'abord) tant que le rapport tient ; il est partiel s'il en manque.
    `summary(n)` ecrit le resume quand `n` faits n'ont pas trouve de place."""
    for kept in range(min(len(facts), 10), -1, -1):
        dropped = len(facts) - kept
        try:
            return SpecialistReport(
                status="ok" if dropped == 0 else "partial",
                summary=summary(dropped),
                facts=list(facts[:kept]),
                confidence=CONFIDENCE,
                freshness=freshness,
                clarification=clarification,
            )
        except ValidationError:
            continue
    raise ValueError("rapport impossible a faire tenir")  # le resume seul depasse : bug


def _more(dropped: int) -> str:
    """Ce qui n'a pas tenu dans le rapport : dit, jamais cache."""
    if dropped == 0:
        return ""
    plural = "s" if dropped > 1 else ""
    return f" {dropped} autre{plural} élément{plural} non détaillé{plural}."


# ---------------------------------------------------------------- journee
def day_report(view: TodayView) -> SpecialistReport:
    """Ce qu'il y a a faire dans la journee en cours."""
    tz = ZoneInfo(view.timezone)
    plan, day = view.plan, view.day
    frame = plan.frame
    facts: list[Fact] = []

    # 1. Le cadre : ce que l'utilisateur a dit de sa journee.
    if frame is not None:
        if frame.off or frame.start is None or frame.end is None:
            text = "pas de travail aujourd'hui"
        else:
            text = f"travail de {_hour(frame.start, tz, day)} à {_hour(frame.end, tz, day)}"
            if frame.breaks:
                text += ", pauses : " + ", ".join(
                    f"{_hour(p.start, tz, day)} - {_hour(p.end, tz, day)}" for p in frame.breaks
                )
        facts.append(
            Fact(
                label="Ta journée",
                value=_short(text, 200),
                data_class="personal",
                source=FRAME_SOURCE,
                measured=True,
            )
        )

    # 2. Les retards : ce qui presse le plus.
    for task in view.overdue[:3]:
        facts.append(
            Fact(
                label="En retard",
                value=_short(f"{task.title}, {_due(task, day)}", 200),
                data_class="personal",
                source=task_source(task),
                measured=True,
            )
        )

    # 3. Le plan, puis l'agenda horaire, dans l'ordre du temps.
    moments: list[tuple[datetime, Fact]] = []
    for block in plan.blocks:
        task = view.tasks[str(block.task_id)]
        moments.append(
            (
                block.start,
                Fact(
                    label=f"{_hour(block.start, tz, day)} - {_hour(block.end, tz, day)}",
                    value=_short(f"travailler sur {task.title}"),
                    data_class="personal",
                    source=PLAN_SOURCE,
                    measured=False,  # une proposition, pas un fait
                ),
            )
        )
    for entry in view.agenda:
        if entry.starts_at is None or entry.ends_at is None:
            continue
        moments.append(
            (entry.starts_at, _agenda_fact(entry, entry.starts_at, entry.ends_at, tz, day))
        )
    moments.sort(key=lambda pair: pair[0])
    facts.extend(fact for _, fact in moments)

    # 4. Ce qui ne peut pas etre place sans une duree.
    for candidate in plan.unestimated[:2]:
        facts.append(
            Fact(
                label="Durée inconnue",
                value=_short(f"{candidate.task.title}, {_due(candidate.task, day)}", 200),
                data_class="personal",
                source=task_source(candidate.task),
                measured=True,
            )
        )

    left = sum(item.minutes for item in plan.leftovers)
    question = _day_question(view)

    def summary(dropped: int) -> str:
        if frame is None:
            opening = "Tu n'as pas dit quand tu travailles aujourd'hui : aucun créneau n'est placé."
        elif frame.off:
            opening = "Jour sans travail : rien n'est proposé."
        elif plan.window is None:
            opening = "Ta plage de travail d'aujourd'hui est finie."
        elif plan.blocks:
            opening = f"Plan proposé : {duration(plan.planned_minutes)} de travail."
        else:
            opening = "Rien à placer dans ta plage de travail."
        counts: list[str] = []
        if view.overdue:
            counts.append(f"{len(view.overdue)} en retard")
        if plan.unestimated:
            counts.append(f"{len(plan.unestimated)} sans durée")
        if left and frame is not None and not frame.off and plan.window is not None:
            counts.append(f"{duration(left)} sans place aujourd'hui")
        middle = f" Tâches : {', '.join(counts)}." if counts else ""
        return f"{opening}{middle}{_more(dropped)}"

    return _fit(summary, facts, question, view.now)


def _agenda_fact(
    entry: AgendaView, start: datetime, end: datetime, tz: ZoneInfo, day: date
) -> Fact:
    where = f" ({entry.location})" if entry.location else ""
    return Fact(
        label=f"{_hour(start, tz, day)} - {_hour(end, tz, day)}",
        value=_short(f"{entry.title}{where}"),
        data_class="personal",
        source="Agenda (calendrier importé)",
        measured=True,
    )


def _day_question(view: TodayView) -> str | None:
    """La seule question qui changerait le plan, s'il y en a une."""
    plan = view.plan
    work = plan.candidates or plan.unestimated
    if plan.frame is None:
        return "Quand comptes-tu travailler aujourd'hui ?" if work else None
    if plan.window is None or not plan.unestimated:  # jour sans travail : pas de fenetre
        return None
    first = plan.unestimated[0].task
    return f"Combien de temps te prendra « {_short(first.title, 120)} » ?"


# -------------------------------------------------------------- echeances
def deadlines_report(view: TodayView) -> SpecialistReport:
    """Retards et echeances des sept prochains jours."""
    day = view.day
    facts = [
        Fact(
            label="En retard",
            value=_short(f"{task.title}, {_due(task, day)}", 200),
            data_class="personal",
            source=task_source(task),
            measured=True,
        )
        for task in view.overdue
    ]
    for task in view.upcoming:
        size = (
            f", durée estimée {duration(task.estimate_minutes)}"
            if task.estimate_minutes is not None
            else ", durée inconnue"
        )
        facts.append(
            Fact(
                label="Échéance",
                value=_short(f"{task.title}, {_due(task, day)}{size}", 200),
                data_class="personal",
                source=task_source(task),
                measured=True,
            )
        )

    def summary(dropped: int) -> str:
        if not view.overdue and not view.upcoming:
            text = "Aucune échéance d'ici une semaine, et rien en retard."
        else:
            text = (
                f"{len(view.upcoming)} échéance{'s' if len(view.upcoming) > 1 else ''} "
                f"d'ici une semaine, {len(view.overdue)} en retard."
            )
        return text + _more(dropped)

    return _fit(summary, facts, None, view.now)
