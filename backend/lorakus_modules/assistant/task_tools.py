"""Outils du chat sur les taches (PR 44, ADR 0018 et 0040) : lister, ajouter, terminer,
supprimer.

Lister (read) s'execute tout de suite. Ajouter et terminer (write), supprimer (sensitive)
affichent une carte dont le texte est ecrit ici, a partir des arguments valides et des
donnees de l'utilisateur. La carte donne l'echeance en date ABSOLUE, calculee dans le fuseau
de l'utilisateur : si le modele a mal compris « vendredi », l'utilisateur le voit avant de
confirmer. Une date deja passee est refusee des la proposition.
"""

import uuid
from datetime import date, timedelta
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
    complete_task,
    delete_task,
    find_open_duplicate,
    get_task,
    list_tasks,
)
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec

LIST_LIMIT: Final = 30
# Une echeance plus lointaine est presque toujours une erreur de date du modele.
MAX_DAYS_AHEAD: Final = 5 * 366

Priority = Literal["haute", "normale", "basse"]
PRIORITY_VALUE: Final[dict[str, int]] = {"haute": 1, "normale": 2, "basse": 3}
PRIORITY_LABEL: Final[dict[int, str]] = {v: k for k, v in PRIORITY_VALUE.items()}


async def _today(call: ToolCall) -> date:
    return local_today(call.ports.clock(), await user_timezone(call.session))


def _error(error: Exception) -> ToolError:
    if isinstance(error, TaskNotFoundError):
        return ToolError("Cette tâche n'existe plus.")
    if isinstance(error, TaskLimitError):
        return ToolError(f"Trop de tâches : {error}.")
    if isinstance(error, TaskStateError):
        return ToolError(f"Impossible : {error}.")
    if isinstance(error, InvalidTaskError):
        return ToolError(f"Tâche refusée : {error}.")
    if isinstance(error, DuplicateTaskError):
        return ToolError("Cette tâche est déjà dans ta liste, avec la même échéance.")
    raise error


async def _task(call: ToolCall, task_id: uuid.UUID) -> TaskView:
    try:
        return await get_task(call.session, task_id)
    except TaskNotFoundError as error:
        raise _error(error) from None


class ListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    which: Literal["ouvertes", "terminees"] = Field(
        default="ouvertes", description="Tâches à faire (par défaut) ou terminées."
    )


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1, max_length=MAX_TITLE_CHARS, description="Intitulé court de la tâche."
    )
    due_on: date | None = Field(
        default=None,
        description="Échéance, date exacte AAAA-MM-JJ calculée depuis la date du jour donnée "
        "plus haut ; absente si l'utilisateur n'en donne pas.",
    )
    estimate_minutes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ESTIMATE_MINUTES,
        description="Durée estimée en minutes, seulement si l'utilisateur la donne.",
    )
    priority: Priority = Field(default="normale", description="Priorité.")


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID = Field(description="Identifiant donné par la liste des tâches.")


class CompleteIn(TaskIn):
    time_spent_minutes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ESTIMATE_MINUTES,
        description="Temps réellement passé, en minutes, seulement si l'utilisateur le donne.",
    )


# ------------------------------------------------------------------ lister
def _line(task: TaskView, today: date) -> dict[str, Any]:
    line: dict[str, Any] = {"id": str(task.id), "titre": task.title}
    if task.due_on is not None:
        line["echeance"] = task.due_on.isoformat()
        line["jour"] = f"{french_date(task.due_on)} ({relative_day(task.due_on, today)})"
        if task.overdue(today):
            line["en_retard"] = True
    if task.estimate_minutes is not None:
        line["duree_estimee"] = duration(task.estimate_minutes)
        if task.estimate_source == "assistant":
            line["duree_estimee_par"] = "lorakus"
    if task.actual_minutes is not None:
        line["temps_passe"] = duration(task.actual_minutes)
    if task.priority != 2:
        line["priorite"] = PRIORITY_LABEL[task.priority]
    if task.parent_id is not None:
        line["sous_tache_de"] = str(task.parent_id)
    if task.open_subtasks:
        line["sous_taches_ouvertes"] = task.open_subtasks
    if task.owner_module is not None:
        line["module"] = task.owner_module
    return line


async def _list(call: ToolCall, args: ListIn) -> dict[str, Any]:
    status = "open" if args.which == "ouvertes" else "done"
    today = await _today(call)
    tasks = await list_tasks(call.session, status, limit=LIST_LIMIT + 1)
    result: dict[str, Any] = {
        "aujourd_hui": today.isoformat(),
        "taches": [_line(t, today) for t in tasks[:LIST_LIMIT]],
    }
    if len(tasks) > LIST_LIMIT:
        result["remarque"] = f"Seules les {LIST_LIMIT} premières sont listées."
    return result


# ----------------------------------------------------------------- ajouter
async def _checked_due(call: ToolCall, due_on: date | None) -> tuple[date | None, date]:
    today = await _today(call)
    if due_on is not None and due_on < today:
        raise ToolError(
            f"L'échéance proposée ({french_date(due_on)}) est déjà passée : vérifie le jour voulu."
        )
    if due_on is not None and due_on > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ToolError("Échéance trop lointaine : vérifie l'année.")
    return due_on, today


async def _add_summary(call: ToolCall, args: AddIn) -> str:
    try:
        title = clean_line(args.title, MAX_TITLE_CHARS)
    except InvalidTaskError as error:
        raise _error(error) from None
    due_on, today = await _checked_due(call, args.due_on)
    # Avant toute carte : une tache deja ouverte (meme titre, meme echeance) n'en montre pas.
    if await find_open_duplicate(call.session, title, due_on) is not None:
        raise _error(DuplicateTaskError(title))
    lines = [f"Ajouter une tâche : « {title} »"]
    if due_on is not None:
        lines.append(f"Échéance : {french_date(due_on)} ({relative_day(due_on, today)})")
    if args.estimate_minutes is not None:
        lines.append(f"Durée estimée : {duration(args.estimate_minutes)}")
    if args.priority != "normale":
        lines.append(f"Priorité : {args.priority}")
    return "\n".join(lines)


async def _add(call: ToolCall, args: AddIn) -> dict[str, Any]:
    new = NewTask(
        title=args.title,
        due_on=args.due_on,
        estimate_minutes=args.estimate_minutes,
        priority=PRIORITY_VALUE[args.priority],
    )
    try:
        task = await add_task(
            call.session,
            call.user_id,
            new,
            source_kind="conversation" if call.origin else "user",
            source_ref=call.origin,
        )
    except (
        DuplicateTaskError,
        InvalidTaskError,
        TaskLimitError,
        TaskNotFoundError,
        TaskStateError,
    ) as error:
        raise _error(error) from None
    return {"message": "Tâche ajoutée.", "id": str(task.id)}


# ---------------------------------------------------------------- terminer
async def _complete_summary(call: ToolCall, args: CompleteIn) -> str:
    task = await _task(call, args.task_id)
    if task.status == "done":
        raise ToolError("Cette tâche est déjà terminée.")
    text = f"Marquer comme terminée : « {task.title} »"
    if task.open_subtasks:
        text += f"\n(et ses {task.open_subtasks} sous-tâches encore ouvertes)"
    if args.time_spent_minutes is not None:
        text += f"\nTemps passé : {duration(args.time_spent_minutes)}"
        if task.estimate_minutes is not None:
            text += f" (prévu : {duration(task.estimate_minutes)})"
    return text


async def _complete(call: ToolCall, args: CompleteIn) -> dict[str, Any]:
    try:
        closed = await complete_task(
            call.session,
            call.user_id,
            args.task_id,
            call.ports.clock(),
            actual_minutes=args.time_spent_minutes,
        )
    except (InvalidTaskError, TaskNotFoundError, TaskStateError) as error:
        raise _error(error) from None
    return {"message": "Tâche terminée.", "taches_closes": closed}


# --------------------------------------------------------------- supprimer
async def _delete_summary(call: ToolCall, args: TaskIn) -> str:
    task = await _task(call, args.task_id)
    if task.owner_module is not None:
        raise ToolError(
            f"Cette tâche vient du module {task.owner_module} : supprime-la depuis sa page."
        )
    text = f"Supprimer la tâche : « {task.title} »"
    if task.open_subtasks:
        text += f"\n(et ses {task.open_subtasks} sous-tâches)"
    return text


async def _delete(call: ToolCall, args: TaskIn) -> dict[str, Any]:
    try:
        await delete_task(call.session, call.user_id, args.task_id)
    except (TaskNotFoundError, TaskStateError) as error:
        raise _error(error) from None
    return {"message": "Tâche supprimée."}


TASK_TOOLS: Final = [
    ToolSpec(
        "assistant.list_tasks",
        "Liste les tâches de l'utilisateur (à faire par défaut, ou terminées), avec leur "
        "échéance, leur retard éventuel et leur identifiant.",
        "read",
        ListIn,
        _list,
        activity="A consulté tes tâches",
    ),
    ToolSpec(
        "assistant.add_task",
        "Propose d'ajouter une tâche. Une carte s'affiche avec la date exacte : rien n'est "
        "enregistré tant que l'utilisateur ne l'a pas confirmée.",
        "write",
        AddIn,
        _add,
        summary=_add_summary,
    ),
    ToolSpec(
        "assistant.complete_task",
        "Propose de marquer une tâche comme terminée (identifiant donné par la liste), avec "
        "le temps réellement passé s'il le donne. Une carte s'affiche : rien ne change tant "
        "que l'utilisateur ne l'a pas confirmée.",
        "write",
        CompleteIn,
        _complete,
        summary=_complete_summary,
    ),
    ToolSpec(
        "assistant.delete_task",
        "Propose de supprimer une tâche personnelle (identifiant donné par la liste). Une "
        "carte s'affiche : rien n'est effacé tant que l'utilisateur ne l'a pas confirmée.",
        "sensitive",
        TaskIn,
        _delete,
        summary=_delete_summary,
    ),
]
