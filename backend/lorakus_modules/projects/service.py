"""Idees, projets et taches de projet (PR 51), au-dessus du planning du Core (ADR 0018).

Regle de la specification d'origine : aider a FINIR des projets plutot qu'en commencer sans
cesse. D'ou une boite d'idees separee des projets (noter une idee ne cree pas de travail),
peu de projets actifs a la fois, et les projets qui dorment (aucune activite depuis 14 jours)
signales plutot qu'oublies.

Chaque tache de projet a SA tache dans le planning du Core, par le port `ModuleTasks`
(`owner_ref` = identifiant de la ligne `proj_tasks`) : le planificateur la place, le chat la
voit. Les deux restent d'accord dans les deux sens, comme pour academic :

- terminer ou supprimer ici met la tache du planning a jour dans la meme transaction ;
- terminer la tache ailleurs (chat) publie `planning.task_completed`, et `on_task_completed`
  termine la tache du projet (events.py).

Toutes les fonctions recoivent une session deja liee a l'utilisateur (RLS) et s'executent
dans la transaction de l'appelant. Aucun LLM, aucun appel reseau.
"""

import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.identity.service import audit
from lorakus.core.planning.service import (
    MAX_ESTIMATE_MINUTES,
    InvalidTaskError,
    ModuleTasks,
    TaskLimitError,
    clean_line,
)
from lorakus_modules.projects.models import Idea, Project, ProjectTask

MODULE_ID: Final = "projects"
TASKS: Final = ModuleTasks(MODULE_ID)

ProjectStatus = Literal["active", "done"]
IdeaStatus = Literal["inbox", "archived"]

MAX_IDEA_CHARS: Final = 500
MAX_IDEAS: Final = 300  # dans la boite, archivees non comprises
MAX_NAME_CHARS: Final = 80
MAX_DESCRIPTION_CHARS: Final = 500
# Titre de la tache du planning = « projet : titre » : 80 + 3 + 110 tiennent dans 200.
MAX_TASK_CHARS: Final = 110
MAX_ACTIVE_PROJECTS: Final = 20
MAX_OPEN_TASKS: Final = 100  # par projet
MAX_LIST: Final = 200
# Au-dela, un projet actif « dort » : la page et le chat le disent.
IDLE_DAYS: Final = 14
MAX_DAYS_AHEAD: Final = 5 * 366
MAX_DAYS_BEHIND: Final = 366


class ProjectsError(Exception):
    """Refus lisible par l'utilisateur (message en francais, tutoiement)."""


class IdeaNotFoundError(Exception):
    """Idee absente ou d'un autre utilisateur (la RLS les confond)."""


class ProjectNotFoundError(Exception):
    """Projet absent ou d'un autre utilisateur."""


class ProjectTaskNotFoundError(Exception):
    """Tache de projet absente ou d'un autre utilisateur."""


@dataclass(frozen=True)
class IdeaView:
    id: uuid.UUID
    text: str
    status: str
    created_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class TaskLine:
    """Une tache d'un projet, avec ce que le planning en sait (echeance, duree)."""

    id: uuid.UUID
    title: str
    status: str
    due_on: date | None
    estimate_minutes: int | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class ProjectView:
    id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    last_activity_at: datetime
    finished_at: datetime | None
    tasks: tuple[TaskLine, ...]  # ouvertes d'abord (par echeance), puis terminees

    @property
    def open_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == "open")

    @property
    def done_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.status == "done")

    def idle_days(self, now: datetime) -> int | None:
        """Jours sans activite d'un projet actif qui dort (14 ou plus), sinon None."""
        if self.status != "active":
            return None
        days = (now - self.last_activity_at).days
        return days if days >= IDLE_DAYS else None


# ------------------------------------------------------------- validation
def _line(text: str, limit: int, empty: str, too_long: str) -> str:
    """Une ligne visible (memes regles que les titres de taches), ou un refus lisible."""
    try:
        value = clean_line(text, max(limit, len(text)))
    except InvalidTaskError:
        raise ProjectsError(empty) from None
    if len(value) > limit:
        raise ProjectsError(too_long)
    return value


def clean_idea(text: str) -> str:
    return _line(
        text,
        MAX_IDEA_CHARS,
        "Écris ton idée.",
        f"Idée trop longue ({MAX_IDEA_CHARS} caractères au plus).",
    )


def clean_name(name: str) -> str:
    return _line(
        name,
        MAX_NAME_CHARS,
        "Donne un nom à ce projet.",
        f"Nom du projet trop long ({MAX_NAME_CHARS} caractères au plus).",
    )


def clean_description(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    return _line(
        text,
        MAX_DESCRIPTION_CHARS,
        "Description vide.",
        f"Description trop longue ({MAX_DESCRIPTION_CHARS} caractères au plus).",
    )


def clean_task_title(title: str) -> str:
    return _line(
        title,
        MAX_TASK_CHARS,
        "Donne un titre à cette tâche.",
        f"Titre trop long ({MAX_TASK_CHARS} caractères au plus).",
    )


def name_key(name: str) -> str:
    """Sans casse, sans accents, espaces regroupes : « Lorakus » et « lorakus » sont le
    meme projet."""
    decomposed = unicodedata.normalize("NFKD", name)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    key = " ".join(bare.casefold().split())
    if not key:
        raise ProjectsError("Donne un nom à ce projet.")
    return key


def check_due(due_on: date, today: date, *, allow_past: bool) -> None:
    """Echeance plausible. Le chat refuse une date passee ; la page accepte une tache deja
    en retard, saisie par l'utilisateur lui-meme."""
    if due_on < today and not allow_past:
        raise ProjectsError("Cette échéance est déjà passée : vérifie le jour voulu.")
    if due_on < today - timedelta(days=MAX_DAYS_BEHIND):
        raise ProjectsError("Échéance trop ancienne : vérifie l'année.")
    if due_on > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ProjectsError("Échéance trop lointaine : vérifie l'année.")


def task_title(project_name: str, title: str) -> str:
    """Titre de la tache du planning : « Lorakus : écrire le README »."""
    return f"{project_name} : {title}"


def _source(source_ref: str | None) -> dict[str, str | None]:
    return {"source_kind": "conversation" if source_ref else "user", "source_ref": source_ref}


def _idea_source(source_ref: str | None, channel: str | None) -> dict[str, str | None]:
    """Provenance d'une idee : la conversation, un canal externe (Telegram), ou la page."""
    if channel is not None:
        return {"source_kind": channel, "source_ref": None}
    return _source(source_ref)


def _idea(row: Idea) -> IdeaView:
    return IdeaView(row.id, row.text, row.status, row.created_at, row.archived_at)


# ------------------------------------------------------------------ idees
async def list_ideas(session: AsyncSession, status: IdeaStatus = "inbox") -> list[IdeaView]:
    """La boite : les plus recentes d'abord ; les archivees, les plus recemment archivees."""
    order = Idea.created_at.desc() if status == "inbox" else Idea.archived_at.desc()
    rows = await session.scalars(
        select(Idea).where(Idea.status == status).order_by(order, Idea.id).limit(MAX_LIST)
    )
    return [_idea(row) for row in rows]


async def find_inbox_idea(session: AsyncSession, text: str) -> uuid.UUID | None:
    """Idee de meme texte deja dans la boite (casse ignoree), ou None."""
    return await session.scalar(
        select(Idea.id)
        .where(Idea.status == "inbox", func.lower(Idea.text) == func.lower(clean_idea(text)))
        .limit(1)
    )


async def add_idea(
    session: AsyncSession,
    user_id: uuid.UUID,
    text: str,
    *,
    source_ref: str | None = None,
    channel: Literal["telegram"] | None = None,
    ip: str | None = None,
) -> IdeaView:
    clean = clean_idea(text)
    if await find_inbox_idea(session, clean) is not None:
        raise ProjectsError("Cette idée est déjà dans ta boîte.")
    count = await session.scalar(
        select(func.count()).select_from(Idea).where(Idea.status == "inbox")
    )
    if (count or 0) >= MAX_IDEAS:
        raise ProjectsError(
            f"{MAX_IDEAS} idées au plus dans la boîte : archives-en avant d'en noter d'autres."
        )
    row = Idea(id=uuid.uuid4(), user_id=user_id, text=clean, **_idea_source(source_ref, channel))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    detail: dict[str, object] = {"idea_id": str(row.id)}
    if channel is not None:
        detail["channel"] = channel
    await audit(session, user_id, "projects.idea_add", "success", ip, detail)
    return _idea(row)


async def _idea_locked(session: AsyncSession, idea_id: uuid.UUID) -> Idea:
    row = await session.get(Idea, idea_id, with_for_update=True)
    if row is None:
        raise IdeaNotFoundError(idea_id)
    return row


async def archive_idea(
    session: AsyncSession,
    user_id: uuid.UUID,
    idea_id: uuid.UUID,
    now: datetime,
    ip: str | None = None,
) -> IdeaView:
    row = await _idea_locked(session, idea_id)
    if row.status != "inbox":
        raise ProjectsError("Cette idée est déjà archivée.")
    row.status = "archived"
    row.archived_at = now
    await session.flush()
    await audit(session, user_id, "projects.idea_archive", "success", ip, {"idea_id": str(row.id)})
    return _idea(row)


async def delete_idea(
    session: AsyncSession, user_id: uuid.UUID, idea_id: uuid.UUID, ip: str | None = None
) -> None:
    row = await _idea_locked(session, idea_id)
    await session.execute(delete(Idea).where(Idea.id == row.id))
    await audit(session, user_id, "projects.idea_delete", "success", ip, {"idea_id": str(row.id)})


# --------------------------------------------------------------- projets
async def _lines(
    session: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[TaskLine]]:
    if not project_ids:
        return {}
    rows = list(
        await session.scalars(
            select(ProjectTask)
            .where(ProjectTask.project_id.in_(project_ids))
            .order_by(ProjectTask.created_at, ProjectTask.id)
        )
    )
    planned = await TASKS.many(session, [str(row.id) for row in rows])
    lines: dict[uuid.UUID, list[TaskLine]] = {pid: [] for pid in project_ids}
    for row in rows:
        task = planned.get(str(row.id))
        lines[row.project_id].append(
            TaskLine(
                id=row.id,
                title=row.title,
                status=row.status,
                due_on=task.due_on if task else None,
                estimate_minutes=task.estimate_minutes if task else None,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
        )
    for items in lines.values():
        # Ouvertes d'abord, par echeance (sans echeance ensuite) ; puis les terminees.
        items.sort(
            key=lambda t: (
                t.status != "open",
                t.due_on or date.max,
                t.created_at,
                str(t.id),
            )
        )
    return lines


def _project(row: Project, tasks: Sequence[TaskLine]) -> ProjectView:
    return ProjectView(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
        last_activity_at=row.last_activity_at,
        finished_at=row.finished_at,
        tasks=tuple(tasks),
    )


async def list_projects(
    session: AsyncSession, status: ProjectStatus = "active"
) -> list[ProjectView]:
    """Actifs : celui qui a le moins bouge d'abord (le plus a risque d'etre oublie) ; termines :
    les plus recents d'abord."""
    order = (
        (Project.last_activity_at, Project.id)
        if status == "active"
        else (Project.finished_at.desc(), Project.id)
    )
    rows = list(
        await session.scalars(
            select(Project).where(Project.status == status).order_by(*order).limit(MAX_LIST)
        )
    )
    lines = await _lines(session, [row.id for row in rows])
    return [_project(row, lines[row.id]) for row in rows]


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectView:
    row = await session.get(Project, project_id)
    if row is None:
        raise ProjectNotFoundError(project_id)
    return _project(row, (await _lines(session, [row.id]))[row.id])


async def find_project(session: AsyncSession, name: str) -> ProjectView | None:
    """Projet de ce nom (sans casse ni accents), ou None."""
    row = await session.scalar(
        select(Project).where(Project.name_key == name_key(clean_name(name)))
    )
    return None if row is None else await get_project(session, row.id)


async def check_new_project(session: AsyncSession, name: str) -> str:
    """Nom nettoye d'un nouveau projet ; refuse un doublon ou un projet actif de trop."""
    clean = clean_name(name)
    if await session.scalar(select(Project.id).where(Project.name_key == name_key(clean))):
        raise ProjectsError("Tu as déjà un projet de ce nom.")
    active = await session.scalar(
        select(func.count()).select_from(Project).where(Project.status == "active")
    )
    if (active or 0) >= MAX_ACTIVE_PROJECTS:
        raise ProjectsError(
            f"{MAX_ACTIVE_PROJECTS} projets actifs au plus : termines-en un avant d'en commencer "
            "un autre."
        )
    return clean


async def add_project(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    description: str | None = None,
    *,
    tasks: Sequence[str] = (),
    idea_id: uuid.UUID | None = None,
    now: datetime | None = None,
    source_ref: str | None = None,
    ip: str | None = None,
) -> ProjectView:
    """Cree un projet, avec ses premieres taches. Depuis une idee de la boite : l'idee
    disparait, son texte devient la description si aucune n'est donnee."""
    clean = await check_new_project(session, name)
    text = clean_description(description)
    titles = [clean_task_title(title) for title in tasks]
    if len({t.casefold() for t in titles}) != len(titles):
        raise ProjectsError("Deux tâches portent le même titre.")
    if len(titles) > MAX_OPEN_TASKS:
        raise ProjectsError(f"{MAX_OPEN_TASKS} tâches ouvertes au plus par projet.")
    if idea_id is not None:
        idea = await _idea_locked(session, idea_id)
        if idea.status != "inbox":
            raise ProjectsError("Cette idée est archivée : rien à transformer.")
        text = text if text is not None else clean_description(idea.text)
        await session.execute(delete(Idea).where(Idea.id == idea.id))
    moment = now or datetime.now(UTC)
    row = Project(
        id=uuid.uuid4(),
        user_id=user_id,
        name=clean,
        name_key=name_key(clean),
        description=text,
        last_activity_at=moment,
        **_source(source_ref),
    )
    session.add(row)
    await session.flush()
    for title in titles:
        await _add_task(session, user_id, row, title, None, None, source_ref, moment)
    await session.refresh(row)
    await audit(
        session,
        user_id,
        "projects.project_add",
        "success",
        ip,
        {"project_id": str(row.id), "tasks": len(titles), "from_idea": idea_id is not None},
    )
    return await get_project(session, row.id)


async def _project_locked(session: AsyncSession, project_id: uuid.UUID) -> Project:
    row = await session.get(Project, project_id, with_for_update=True)
    if row is None:
        raise ProjectNotFoundError(project_id)
    return row


async def finish_project(
    session: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    now: datetime,
    ip: str | None = None,
) -> ProjectView:
    """Termine un projet et ses taches encore ouvertes (et leurs taches du planning)."""
    row = await _project_locked(session, project_id)
    if row.status != "active":
        raise ProjectsError("Ce projet est déjà terminé.")
    opened = list(
        await session.scalars(
            select(ProjectTask).where(
                ProjectTask.project_id == row.id, ProjectTask.status == "open"
            )
        )
    )
    for task in opened:
        task.status = "done"
        task.completed_at = now
        await TASKS.complete(session, str(task.id), now)
    row.status = "done"
    row.finished_at = now
    row.last_activity_at = now
    await session.flush()
    await audit(
        session,
        user_id,
        "projects.project_finish",
        "success",
        ip,
        {"project_id": str(row.id), "closed_tasks": len(opened)},
    )
    return await get_project(session, row.id)


async def delete_project(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, ip: str | None = None
) -> int:
    """Supprime un projet, ses taches et leurs taches du planning ; rend leur nombre."""
    row = await _project_locked(session, project_id)
    ids = list(
        await session.scalars(select(ProjectTask.id).where(ProjectTask.project_id == row.id))
    )
    for task_id in ids:
        await TASKS.delete(session, str(task_id))
    await session.execute(delete(Project).where(Project.id == row.id))  # cascade
    await audit(
        session,
        user_id,
        "projects.project_delete",
        "success",
        ip,
        {"project_id": str(project_id), "tasks": len(ids)},
    )
    return len(ids)


# ------------------------------------------------------- taches de projet
async def _add_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    project: Project,
    title: str,
    due_on: date | None,
    estimate_minutes: int | None,
    source_ref: str | None,
    now: datetime,
) -> ProjectTask:
    row = ProjectTask(
        id=uuid.uuid4(),
        user_id=user_id,
        project_id=project.id,
        title=title,
        # L'heure reelle de l'insertion, pas celle de la transaction : les premieres taches
        # d'un projet, creees ensemble, gardent leur ordre.
        created_at=func.clock_timestamp(),
        **_source(source_ref),
    )
    session.add(row)
    await session.flush()
    try:
        await TASKS.upsert(
            session,
            user_id,
            str(row.id),
            task_title(project.name, title),
            due_on=due_on,
            estimate_minutes=estimate_minutes,
        )
    except (TaskLimitError, InvalidTaskError) as error:
        raise ProjectsError(f"Tâche refusée par le planning : {error}.") from None
    project.last_activity_at = now
    return row


async def check_new_task(session: AsyncSession, project_id: uuid.UUID, title: str) -> str:
    """Titre nettoye d'une nouvelle tache ; refuse un doublon ouvert ou une tache de trop."""
    clean = clean_task_title(title)
    duplicate = await session.scalar(
        select(ProjectTask.id).where(
            ProjectTask.project_id == project_id,
            ProjectTask.status == "open",
            func.lower(ProjectTask.title) == func.lower(clean),
        )
    )
    if duplicate is not None:
        raise ProjectsError("Cette tâche est déjà ouverte dans ce projet.")
    opened = await session.scalar(
        select(func.count())
        .select_from(ProjectTask)
        .where(ProjectTask.project_id == project_id, ProjectTask.status == "open")
    )
    if (opened or 0) >= MAX_OPEN_TASKS:
        raise ProjectsError(f"{MAX_OPEN_TASKS} tâches ouvertes au plus par projet.")
    return clean


async def add_project_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    *,
    due_on: date | None = None,
    estimate_minutes: int | None = None,
    now: datetime | None = None,
    source_ref: str | None = None,
    ip: str | None = None,
) -> ProjectView:
    project = await _project_locked(session, project_id)
    if project.status != "active":
        raise ProjectsError("Ce projet est terminé : rouvre-en un autre pour y ajouter du travail.")
    clean = await check_new_task(session, project.id, title)
    if estimate_minutes is not None and not 1 <= estimate_minutes <= MAX_ESTIMATE_MINUTES:
        raise ProjectsError("Durée estimée invalide.")
    row = await _add_task(
        session,
        user_id,
        project,
        clean,
        due_on,
        estimate_minutes,
        source_ref,
        now or datetime.now(UTC),
    )
    await session.flush()
    await audit(session, user_id, "projects.task_add", "success", ip, {"task_id": str(row.id)})
    return await get_project(session, project.id)


async def _task_locked(session: AsyncSession, task_id: uuid.UUID) -> tuple[ProjectTask, Project]:
    row = await session.get(ProjectTask, task_id, with_for_update=True)
    if row is None:
        raise ProjectTaskNotFoundError(task_id)
    project = await _project_locked(session, row.project_id)
    return row, project


async def complete_project_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    now: datetime,
    ip: str | None = None,
    *,
    actual_minutes: int | None = None,
) -> ProjectView:
    row, project = await _task_locked(session, task_id)
    if row.status != "open":
        raise ProjectsError("Cette tâche est déjà terminée.")
    if actual_minutes is not None and not 1 <= actual_minutes <= MAX_ESTIMATE_MINUTES:
        raise ProjectsError("Le temps passé va de 1 minute à 7 jours.")
    row.status = "done"
    row.completed_at = now
    project.last_activity_at = now
    await session.flush()
    await TASKS.complete(session, str(row.id), now, actual_minutes=actual_minutes)
    await audit(session, user_id, "projects.task_complete", "success", ip, {"task_id": str(row.id)})
    return await get_project(session, project.id)


async def delete_project_task(
    session: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID, ip: str | None = None
) -> None:
    row, _ = await _task_locked(session, task_id)
    await TASKS.delete(session, str(row.id))
    await session.execute(delete(ProjectTask).where(ProjectTask.id == row.id))
    await audit(session, user_id, "projects.task_delete", "success", ip, {"task_id": str(row.id)})


async def on_task_completed(session: AsyncSession, owner_ref: str) -> bool:
    """L'utilisateur a termine, ailleurs (chat), la tache du planning d'une tache de projet :
    elle l'est aussi ici, et le projet a bouge.

    L'evenement n'est qu'un signal : l'etat est relu dans le planning. Rejouable sans effet ;
    rend True si une tache de projet vient d'etre terminee.
    """
    try:
        task_id = uuid.UUID(owner_ref)
    except ValueError:
        return False
    task = await TASKS.get(session, str(task_id))
    if task is None or task.status != "done" or task.completed_at is None:
        return False
    row = await session.get(ProjectTask, task_id, with_for_update=True)
    if row is None or row.status != "open":
        return False
    project = await _project_locked(session, row.project_id)
    row.status = "done"
    row.completed_at = task.completed_at
    project.last_activity_at = max(project.last_activity_at, task.completed_at)
    await session.flush()
    return True
