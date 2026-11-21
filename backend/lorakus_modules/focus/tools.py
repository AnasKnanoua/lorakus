"""Outil du chat du Sergent (PR 50, ADR 0040) : decouper une tache en etapes.

Le decoupage est propose par le modele dans l'appel deja fait pour la reponse (aucun appel
de plus, ADR 0025) ; le code verifie tout, ecrit la carte, et rien n'est cree avant le clic.
Les etapes sont des sous-taches du Core : le planificateur les place a la place de leur
tache (regle 3), avec l'echeance de la tache si elles n'en ont pas.

Verifie avant toute carte : la tache existe, est ouverte, n'est pas deja une etape, n'a pas
deja ete decoupee ; 2 a 8 etapes, titres lisibles et distincts, durees bornees. Une duree
d'etape est celle de l'utilisateur ou une estimation de Lorakus : la carte dit laquelle.
"""

import uuid
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from lorakus.core.account.clock import local_today
from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.planning.service import (
    MAX_ESTIMATE_MINUTES,
    MAX_TITLE_CHARS,
    DuplicateTaskError,
    InvalidTaskError,
    NewTask,
    TaskLimitError,
    TaskNotFoundError,
    TaskStateError,
    TaskView,
    add_task,
    clean_line,
    get_task,
)
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec

MIN_STEPS: Final = 2
MAX_STEPS: Final = 8


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS, description="Titre de l'étape.")
    minutes: int | None = Field(
        default=None, ge=1, le=MAX_ESTIMATE_MINUTES, description="Durée de l'étape, en minutes."
    )


class SplitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID = Field(description="Identifiant donné par la liste des tâches ou le plan.")
    steps: list[StepIn] = Field(
        min_length=MIN_STEPS, max_length=MAX_STEPS, description="Les étapes, dans l'ordre."
    )
    estimate_by: Literal["utilisateur", "lorakus"] = Field(
        default="lorakus",
        description="Qui donne les durées des étapes : l'utilisateur, ou toi (lorakus).",
    )


async def _checked(call: ToolCall, args: SplitIn) -> tuple[TaskView, list[str]]:
    """La tache a decouper et les titres nettoyes ; ToolError avec un message pour le modele."""
    try:
        task = await get_task(call.session, args.task_id)
    except TaskNotFoundError:
        raise ToolError("Cette tâche n'existe plus.") from None
    if task.status != "open":
        raise ToolError("Cette tâche est déjà terminée.")
    if task.parent_id is not None:
        raise ToolError("C'est déjà une étape : une étape ne se découpe pas.")
    if task.subtasks:
        raise ToolError("Cette tâche est déjà découpée en étapes.")
    try:
        titles = [clean_line(step.title, MAX_TITLE_CHARS) for step in args.steps]
    except InvalidTaskError as error:
        raise ToolError(f"Étape refusée : {error}.") from None
    if len({title.casefold() for title in titles}) != len(titles):
        raise ToolError("Deux étapes portent le même titre.")
    return task, titles


async def _summary(call: ToolCall, args: SplitIn) -> str:
    task, titles = await _checked(call, args)
    lines = [f"Découper « {task.title} » en {len(titles)} étapes :"]
    for number, (title, step) in enumerate(zip(titles, args.steps, strict=True), start=1):
        size = f" ({duration(step.minutes)})" if step.minutes is not None else ""
        lines.append(f"{number}. {title}{size}")
    sized = [step.minutes for step in args.steps if step.minutes is not None]
    if sized:
        by = "estimation de Lorakus" if args.estimate_by == "lorakus" else "tes durées"
        lines.append(f"Total : {duration(sum(sized))} ({by})")
        if task.estimate_minutes is not None:
            lines.append(f"Durée prévue pour la tâche : {duration(task.estimate_minutes)}")
    if task.due_on is not None:
        today = local_today(call.ports.clock(), await user_timezone(call.session))
        lines.append(
            f"Échéance des étapes : {french_date(task.due_on)} ({relative_day(task.due_on, today)})"
        )
    return "\n".join(lines)


async def _split(call: ToolCall, args: SplitIn) -> dict[str, Any]:
    task, titles = await _checked(call, args)
    source: Literal["user", "assistant"] = "assistant" if args.estimate_by == "lorakus" else "user"
    try:
        for number, (title, step) in enumerate(zip(titles, args.steps, strict=True), start=1):
            await add_task(
                call.session,
                call.user_id,
                NewTask(
                    title=title,
                    estimate_minutes=step.minutes,
                    parent_id=task.id,
                    estimate_source=source,
                    step_number=number,  # l'ordre de travail, garde par le planificateur
                ),
                source_kind="conversation" if call.origin else "user",
                source_ref=call.origin,
            )
    except (
        DuplicateTaskError,
        TaskLimitError,
        TaskStateError,
        TaskNotFoundError,
        InvalidTaskError,
    ) as error:
        raise ToolError(f"Découpage impossible : {error}.") from None
    return {
        "message": f"{len(titles)} étapes créées : le plan du jour les place à la place de la "
        "tâche."
    }


TOOLS: Final = [
    ToolSpec(
        "focus.split_task",
        "Propose de découper une tâche longue en 2 à 8 étapes (identifiant donné par la liste "
        "des tâches ou le plan), avec une durée par étape si tu peux l'estimer. Propose-le "
        "quand une tâche dépasse quelques heures, sans insister. Une carte s'affiche : rien "
        "n'est créé tant que l'utilisateur ne l'a pas confirmée.",
        "write",
        SplitIn,
        _split,
        summary=_summary,
    ),
]
