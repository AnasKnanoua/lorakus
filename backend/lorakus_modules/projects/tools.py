"""Outils du chat du module projects (PR 51, ADR 0040).

- `projects.list` (read) : les projets actifs (avancement, taches ouvertes, projet qui dort)
  et les dernieres idees de la boite. Noms, titres et idees passent par inert() : ce sont des
  donnees, pas des instructions.
- `projects.add_idea` (write) : noter une idee dans la boite, en deux secondes.
- `projects.add_project` (write) : commencer un projet, avec ses premieres taches.
- `projects.add_task` (write) : ajouter une tache a un projet existant.

Le texte des cartes est ecrit ici, a partir des arguments valides, jamais par le modele.
Refuses avant toute carte : doublon, projet inconnu ou termine, limite atteinte, echeance
passee ou trop lointaine. Regle du module : aider a finir avant de commencer. La carte d'un
nouveau projet rappelle donc les projets actifs qui dorment.
"""

from datetime import UTC, date, datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from lorakus.core.account.clock import local_today
from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.planning.service import MAX_ESTIMATE_MINUTES
from lorakus.core.tools.inert import inert
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec
from lorakus_modules.projects.service import (
    MAX_DESCRIPTION_CHARS,
    MAX_IDEA_CHARS,
    MAX_NAME_CHARS,
    MAX_TASK_CHARS,
    ProjectsError,
    ProjectView,
    add_idea,
    add_project,
    add_project_task,
    check_due,
    check_new_project,
    check_new_task,
    clean_description,
    clean_idea,
    clean_task_title,
    find_inbox_idea,
    find_project,
    list_ideas,
    list_projects,
)

MAX_FIRST_TASKS: Final = 8
LIST_IDEAS: Final = 10


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdeaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1,
        max_length=MAX_IDEA_CHARS,
        description="L'idée, dans les mots de l'utilisateur.",
    )


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS, description="Nom court du projet.")
    description: str | None = Field(
        default=None,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Le but, en une ou deux phrases.",
    )
    tasks: list[str] = Field(
        default_factory=list[str],
        max_length=MAX_FIRST_TASKS,
        description="Premières tâches, dans l'ordre, seulement si l'utilisateur en parle ou "
        "les accepte.",
    )


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(
        min_length=1, max_length=MAX_NAME_CHARS, description="Nom du projet, tel que dit."
    )
    title: str = Field(min_length=1, max_length=MAX_TASK_CHARS, description="La tâche.")
    due_on: date | None = Field(
        default=None, description="AAAA-MM-JJ, seulement si l'utilisateur donne une échéance."
    )
    estimate_minutes: int | None = Field(
        default=None, ge=1, le=MAX_ESTIMATE_MINUTES, description="Durée, si elle est donnée."
    )


def _now(call: ToolCall) -> datetime:
    return call.ports.clock().astimezone(UTC)


# ----------------------------------------------------------------- liste
async def _list(call: ToolCall, _: NoArgs) -> dict[str, Any]:
    now = _now(call)
    projects = await list_projects(call.session, "active")
    ideas = await list_ideas(call.session)

    def line(project: ProjectView) -> dict[str, Any]:
        item: dict[str, Any] = {
            "nom": inert(project.name),
            "taches_faites": project.done_tasks,
            "taches_ouvertes": [inert(t.title) for t in project.tasks if t.status == "open"][:10],
        }
        if project.description:
            item["but"] = inert(project.description)
        idle = project.idle_days(now)
        if idle is not None:
            item["sans_activite_depuis_jours"] = idle
        return item

    return {
        "projets_actifs": [line(p) for p in projects],
        "idees_dans_la_boite": len(ideas),
        "dernieres_idees": [inert(i.text) for i in ideas[:LIST_IDEAS]],
    }


# ----------------------------------------------------------------- idee
async def _idea_summary(call: ToolCall, args: IdeaIn) -> str:
    try:
        text = clean_idea(args.text)
        if await find_inbox_idea(call.session, text) is not None:
            raise ProjectsError("Cette idée est déjà dans ta boîte.")
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    return f"Noter une idée : « {text} »"


async def _idea(call: ToolCall, args: IdeaIn) -> dict[str, Any]:
    try:
        await add_idea(call.session, call.user_id, args.text, source_ref=call.origin)
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    return {"message": "Idée notée dans la boîte."}


# ---------------------------------------------------------------- projet
async def _project_summary(call: ToolCall, args: ProjectIn) -> str:
    try:
        name = await check_new_project(call.session, args.name)
        description = clean_description(args.description)
        titles = [clean_task_title(t) for t in args.tasks]
        if len({t.casefold() for t in titles}) != len(titles):
            raise ProjectsError("Deux tâches portent le même titre.")
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    lines = [f"Commencer le projet « {name} »"]
    if description:
        lines.append(f"But : {description}")
    lines.extend(f"{n}. {title}" for n, title in enumerate(titles, start=1))
    now = _now(call)
    sleeping = [p.name for p in await list_projects(call.session, "active") if p.idle_days(now)]
    if sleeping:
        # Aider a finir avant de commencer : ce qui dort se voit avant le clic.
        lines.append(f"Projets qui dorment : {', '.join(sleeping[:3])}")
    return "\n".join(lines)


async def _project(call: ToolCall, args: ProjectIn) -> dict[str, Any]:
    try:
        await add_project(
            call.session,
            call.user_id,
            args.name,
            args.description,
            tasks=args.tasks,
            now=_now(call),
            source_ref=call.origin,
        )
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    return {"message": "Projet créé : ses tâches sont dans le planning."}


# ----------------------------------------------------------------- tache
async def _task_checked(call: ToolCall, args: TaskIn) -> tuple[ProjectView, str, date | None]:
    today = local_today(call.ports.clock(), await user_timezone(call.session))
    try:
        project = await find_project(call.session, args.project)
        if project is None:
            raise ProjectsError(
                f"Aucun projet ne s'appelle « {args.project} » : vérifie le nom, ou propose "
                "d'abord de le créer."
            )
        if project.status != "active":
            raise ProjectsError("Ce projet est terminé.")
        title = await check_new_task(call.session, project.id, args.title)
        if args.due_on is not None:
            check_due(args.due_on, today, allow_past=False)
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    return project, title, today


async def _task_summary(call: ToolCall, args: TaskIn) -> str:
    project, title, today = await _task_checked(call, args)
    lines = [f"Ajouter au projet « {project.name} » : « {title} »"]
    if args.due_on is not None and today is not None:
        lines.append(f"Échéance : {french_date(args.due_on)} ({relative_day(args.due_on, today)})")
    if args.estimate_minutes is not None:
        lines.append(f"Durée estimée : {duration(args.estimate_minutes)}")
    return "\n".join(lines)


async def _task(call: ToolCall, args: TaskIn) -> dict[str, Any]:
    project, title, _ = await _task_checked(call, args)
    try:
        await add_project_task(
            call.session,
            call.user_id,
            project.id,
            title,
            due_on=args.due_on,
            estimate_minutes=args.estimate_minutes,
            now=_now(call),
            source_ref=call.origin,
        )
    except ProjectsError as error:
        raise ToolError(str(error)) from None
    return {"message": "Tâche ajoutée au projet et au planning."}


TOOLS: Final = [
    ToolSpec(
        "projects.list",
        "Lit les projets actifs (avancement, tâches ouvertes, projet sans activité depuis "
        "longtemps) et les dernières idées de la boîte.",
        "read",
        NoArgs,
        _list,
        activity="A regardé tes projets",
    ),
    ToolSpec(
        "projects.add_idea",
        "Propose de noter une idée dans la boîte d'idées (sans créer de travail). À préférer "
        "à un projet tant que l'utilisateur ne dit pas vouloir s'y mettre. Une carte s'affiche : "
        "rien n'est noté sans sa confirmation.",
        "write",
        IdeaIn,
        _idea,
        summary=_idea_summary,
    ),
    ToolSpec(
        "projects.add_project",
        "Propose de commencer un projet, avec ses premières tâches si l'utilisateur les donne "
        "ou les accepte. Aide à finir avant de commencer : si des projets dorment, dis-le. Une "
        "carte s'affiche : rien n'est créé sans sa confirmation.",
        "write",
        ProjectIn,
        _project,
        summary=_project_summary,
    ),
    ToolSpec(
        "projects.add_task",
        "Propose d'ajouter une tâche à un projet existant (nom du projet tel que dit). Une "
        "carte s'affiche : rien n'est ajouté sans sa confirmation.",
        "write",
        TaskIn,
        _task,
        summary=_task_summary,
    ),
]
