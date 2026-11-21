"""Outils du chat pour organiser la journee (PR 49, ADR 0018 et 0040).

Les horaires de l'utilisateur changent tous les jours. Lorakus ne suppose donc rien : il
demande, l'utilisateur repond comme il parle (« je bosse de 15 h a 3 h, je mange vers
22 h », « nuit blanche », « rien aujourd'hui »), et le modele le traduit en arguments. Le
code valide, ecrit la carte, et rien n'est enregistre avant le clic. Le plan, lui, est
toujours calcule par le planificateur (des regles), jamais par le modele.

- `assistant.plan_today` (read) : le cadre du jour, le plan propose heure par heure, les
  taches sans duree (« a estimer ») et ce qui ne tient pas. Le modele s'en sert pour
  expliquer la journee ; il ne place rien lui-meme.
- `assistant.set_day` (write) : le cadre d'aujourd'hui ou de demain.
- `assistant.set_estimate` (write) : la duree d'une tache, donnee par l'utilisateur ou
  estimee par Lorakus ; la carte dit laquelle des deux.

Titres de taches et de creneaux passes par inert() : ce sont des donnees.
"""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.planning.days import (
    BreakKind,
    DayFrame,
    InvalidFrameError,
    build_frame,
    check_not_over,
    current_day,
    day_off,
    frame_lines,
    get_frame,
    set_frame,
)
from lorakus.core.planning.service import (
    MAX_ESTIMATE_MINUTES,
    InvalidTaskError,
    TaskNotFoundError,
    TaskStateError,
    get_task,
    set_estimate,
)
from lorakus.core.planning.today import read_today
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec
from lorakus_modules.assistant.prompts import inert

HOUR: Final = r"^([01]\d|2[0-3]):[0-5]\d$"
KIND: Final[dict[str, BreakKind]] = {
    "repas": "meal",
    "pause": "break",
    "sport": "sport",
    "autre": "other",
}


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["repas", "pause", "sport", "autre"] = Field(description="Nature de la pause.")
    start: str = Field(pattern=HOUR, description="HH:MM, début.")
    end: str = Field(pattern=HOUR, description="HH:MM, fin.")


class DayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Literal["aujourd_hui", "demain"] = Field(
        default="aujourd_hui",
        description="aujourd_hui : la journée en cours (celle de la veille tant qu'une nuit de "
        "travail n'est pas finie) ; demain : la suivante.",
    )
    no_work: bool = Field(
        default=False, description="true si l'utilisateur ne travaille pas ce jour-là."
    )
    start: str | None = Field(
        default=None, pattern=HOUR, description="HH:MM, début de la plage de travail."
    )
    end: str | None = Field(
        default=None,
        pattern=HOUR,
        description="HH:MM, fin de la plage ; plus tôt que le début : le lendemain (nuit).",
    )
    breaks: list[PauseIn] = Field(
        default_factory=list[PauseIn],
        max_length=6,
        description="Repas, sport ou pauses que l'utilisateur annonce dans la plage.",
    )


class EstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID = Field(description="Identifiant donné par la liste des tâches ou le plan.")
    minutes: int = Field(ge=1, le=MAX_ESTIMATE_MINUTES, description="Durée de travail, en minutes.")
    estimate_by: Literal["utilisateur", "lorakus"] = Field(
        description="utilisateur : la durée qu'il a donnée ; lorakus : ton estimation, "
        "qu'il confirmera sur la carte."
    )


# ---------------------------------------------------------------- lecture
def _at(moment: datetime, tz: ZoneInfo, day: date) -> dict[str, Any]:
    local = moment.astimezone(tz)
    line: dict[str, Any] = {"heure": f"{local:%H:%M}"}
    if local.date() > day:
        line["lendemain"] = True
    return line


async def _plan(call: ToolCall, _: NoArgs) -> dict[str, Any]:
    now = call.ports.clock()
    tz = await user_timezone(call.session)
    view = await read_today(call.session, now)
    plan, day = view.plan, view.day
    titles = {key: inert(task.title) for key, task in view.tasks.items()}
    result: dict[str, Any] = {
        "jour": french_date(day),
        "maintenant": f"{now.astimezone(tz):%H:%M}",
    }
    if plan.frame is None:
        result["cadre"] = (
            "aucun : l'utilisateur n'a pas dit quand il travaille ce jour-là. Aucun créneau "
            "n'est proposé tant qu'il ne l'a pas dit : demande-lui, sans supposer d'heure."
        )
    else:
        result["cadre"] = frame_lines(plan.frame, tz)
        if plan.window is None and not plan.frame.off:
            result["remarque"] = "La plage de travail de ce jour est finie."
    result["agenda"] = [
        {
            "titre": inert(e.title),
            "debut": _at(e.starts_at, tz, day),
            "fin": _at(e.ends_at, tz, day),
        }
        for e in view.agenda
        if e.starts_at is not None and e.ends_at is not None
    ]
    result["plan"] = [
        {
            "tache": titles[str(b.task_id)],
            "id": str(b.task_id),
            "debut": _at(b.start, tz, day),
            "fin": _at(b.end, tz, day),
        }
        for b in plan.blocks
    ]
    result["travail_propose"] = duration(plan.planned_minutes)

    def due(when: date | None) -> str:
        return "aucune" if when is None else f"{french_date(when)} ({relative_day(when, day)})"

    result["a_estimer"] = [
        {"tache": titles[str(c.task.id)], "id": str(c.task.id), "echeance": due(c.due_on)}
        for c in plan.unestimated
    ]
    result["sans_place"] = [
        {
            "tache": titles[str(left.task_id)],
            "id": str(left.task_id),
            "reste": duration(left.minutes),
        }
        for left in plan.leftovers
    ]
    return result


# ------------------------------------------------------------ cadre du jour
def _time(raw: str) -> time:
    return time.fromisoformat(raw)


async def _frame(call: ToolCall, args: DayIn) -> tuple[DayFrame, DayFrame | None, ZoneInfo]:
    """Le cadre propose (valide) et l'actuel ; ToolError avec un message pour le modele."""
    now = call.ports.clock()
    tz = await user_timezone(call.session)
    day = await current_day(call.session, now, tz)
    if args.day == "demain":
        day += timedelta(days=1)
    if args.no_work:
        if args.start or args.end or args.breaks:
            raise ToolError(
                "Un jour sans travail n'a ni horaire ni pause : choisis l'un ou l'autre."
            )
        frame = day_off(day)
    else:
        missing = [name for name in ("start", "end") if getattr(args, name) is None]
        if missing:
            raise ToolError(
                f"Il manque : {', '.join(missing)}. Demande à l'utilisateur quand il travaille "
                "plutôt que de l'inventer."
            )
        try:
            frame = build_frame(
                day,
                tz,
                _time(args.start or ""),
                _time(args.end or ""),
                [(KIND[p.kind], _time(p.start), _time(p.end)) for p in args.breaks],
            )
            check_not_over(frame, now)
        except InvalidFrameError as error:
            raise ToolError(str(error)) from None
    return frame, await get_frame(call.session, day), tz


async def _day_summary(call: ToolCall, args: DayIn) -> str:
    frame, before, tz = await _frame(call, args)
    if frame == before:
        raise ToolError("C'est déjà le cadre de ce jour.")
    lines = [f"Ta journée du {french_date(frame.day)}", *frame_lines(frame, tz)]
    if before is not None:
        lines.append("Remplace : " + " ; ".join(frame_lines(before, tz)))
    return "\n".join(lines)


async def _day(call: ToolCall, args: DayIn) -> dict[str, Any]:
    frame, _, _ = await _frame(call, args)
    await set_frame(call.session, call.user_id, frame, source_ref=call.origin)
    return {
        "message": "Journée enregistrée. Relis le plan avec l'outil du plan du jour avant "
        "d'en parler."
    }


# ------------------------------------------------------------------ duree
def _task_error(error: Exception) -> ToolError:
    if isinstance(error, TaskNotFoundError):
        return ToolError("Cette tâche n'existe plus.")
    if isinstance(error, TaskStateError):
        return ToolError("Cette tâche est déjà terminée.")
    if isinstance(error, InvalidTaskError):
        return ToolError(f"Durée refusée : {error}.")
    raise error


async def _estimate_summary(call: ToolCall, args: EstimateIn) -> str:
    try:
        task = await get_task(call.session, args.task_id)
    except TaskNotFoundError as error:
        raise _task_error(error) from None
    if task.status != "open":
        raise ToolError("Cette tâche est déjà terminée.")
    if task.estimate_minutes == args.minutes:
        raise ToolError(f"C'est déjà sa durée : {duration(args.minutes)}.")
    by = " (estimation de Lorakus)" if args.estimate_by == "lorakus" else ""
    before = "aucune" if task.estimate_minutes is None else duration(task.estimate_minutes)
    return "\n".join(
        [
            f"Durée de « {task.title} » : {duration(args.minutes)}{by}",
            f"Actuellement : {before}",
        ]
    )


async def _estimate(call: ToolCall, args: EstimateIn) -> dict[str, Any]:
    source: Literal["user", "assistant"] = "assistant" if args.estimate_by == "lorakus" else "user"
    try:
        await set_estimate(call.session, call.user_id, args.task_id, args.minutes, source)
    except (TaskNotFoundError, TaskStateError, InvalidTaskError) as error:
        raise _task_error(error) from None
    return {"message": "Durée enregistrée : le plan du jour en tient compte."}


DAY_TOOLS: Final = [
    ToolSpec(
        "assistant.plan_today",
        "Lit la journée en cours : le cadre donné par l'utilisateur (ou son absence), "
        "l'agenda, le plan de travail proposé heure par heure par le planificateur, les "
        "tâches sans durée à estimer et ce qui ne tient pas. À lire avant de parler de la "
        "journée ou de ce qu'il y a à faire.",
        "read",
        NoArgs,
        _plan,
        activity="A regardé ta journée",
    ),
    ToolSpec(
        "assistant.set_day",
        "Propose d'enregistrer le cadre d'une journée quand l'utilisateur dit quand il "
        "travaille (« je bosse de 15 h à 3 h », « nuit blanche jusqu'à 6 h », « je mange vers "
        "22 h », « pas de travail demain »). Ça ne vaut que pour ce jour. Une carte "
        "s'affiche : rien n'est enregistré tant qu'il ne l'a pas confirmée.",
        "write",
        DayIn,
        _day,
        summary=_day_summary,
    ),
    ToolSpec(
        "assistant.set_estimate",
        "Propose d'enregistrer la durée de travail d'une tâche : celle que l'utilisateur "
        "donne, ou ton estimation s'il te la demande. Une carte s'affiche : rien n'est "
        "enregistré tant qu'il ne l'a pas confirmée. Un appel par tâche.",
        "write",
        EstimateIn,
        _estimate,
        summary=_estimate_summary,
    ),
]
