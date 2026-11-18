"""Taches et agenda du Core (ADR 0018) : ports `Tasks` et `Agenda`.

Toutes les fonctions recoivent une session deja liee a l'utilisateur (RLS) : elles
s'executent dans la transaction de l'appelant. Une carte de confirmation du chat cree donc
la tache dans la meme transaction que sa propre decision (ADR 0040, regle 7).

Deux portes d'entree :
- l'utilisateur (API, outils du chat) : ses taches personnelles, et terminer ou consulter
  celles de ses modules ;
- un module, par `ModuleTasks(module_id)` et `ModuleAgenda(module_id)` : uniquement les
  lignes qu'il possede. Une tache d'academic n'est jamais modifiee par projects.

Aucun LLM, aucun appel reseau : des regles et PostgreSQL.
"""

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import day_bounds
from lorakus.core.identity.service import audit
from lorakus.core.planning.models import AgendaEntry, Task

TaskStatus = Literal["open", "done"]
SourceKind = Literal["user", "conversation", "module"]

MAX_TITLE_CHARS: Final = 200
MAX_NOTES_CHARS: Final = 2000
MAX_OPEN_TASKS: Final = 500
MAX_SUBTASKS: Final = 20
MAX_ESTIMATE_MINUTES: Final = 7 * 24 * 60
MAX_LIST: Final = 200
MAX_ENTRIES_PER_SOURCE: Final = 2000
MAX_LOCATION_CHARS: Final = 200
MODULE_ID: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class InvalidTaskError(ValueError):
    """Tache refusee (titre vide ou trop long, duree ou priorite hors bornes...)."""


class TaskNotFoundError(Exception):
    """Tache absente, d'un autre utilisateur (la RLS les confond) ou d'un autre module."""


class TaskLimitError(Exception):
    """Trop de taches ouvertes, ou de sous-taches pour un meme parent."""


class TaskStateError(Exception):
    """Action impossible dans l'etat de la tache (deja terminee, sous-tache d'une sous-tache)."""


class InvalidAgendaEntryError(ValueError):
    """Creneau refuse (fin avant debut, titre vide, doublon dans un meme envoi...)."""


def clean_line(text: str, limit: int, what: str = "titre") -> str:
    """Une ligne lisible : caracteres invisibles et de controle retires, espaces regroupes."""
    visible = "".join(
        " " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c
        for c in unicodedata.normalize("NFC", text)
        if unicodedata.category(c) != "Cf"
    )
    value = " ".join(visible.split())
    if not value:
        raise InvalidTaskError(f"{what} vide")
    if len(value) > limit:
        raise InvalidTaskError(f"{what} : {limit} caracteres au plus")
    return value


def clean_notes(text: str | None) -> str | None:
    if text is None:
        return None
    value = "".join(
        c for c in unicodedata.normalize("NFC", text) if unicodedata.category(c) != "Cf"
    ).strip()
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise InvalidTaskError("notes : caracteres de controle interdits")
    if len(value) > MAX_NOTES_CHARS:
        raise InvalidTaskError(f"notes : {MAX_NOTES_CHARS} caracteres au plus")
    return value or None


def _check_numbers(priority: int, estimate_minutes: int | None) -> None:
    if priority not in (1, 2, 3):
        raise InvalidTaskError("priorite : 1 (haute), 2 (normale) ou 3 (basse)")
    if estimate_minutes is not None and not 1 <= estimate_minutes <= MAX_ESTIMATE_MINUTES:
        raise InvalidTaskError(f"duree estimee : de 1 a {MAX_ESTIMATE_MINUTES} minutes")


@dataclass(frozen=True)
class NewTask:
    """Ce qu'il faut pour creer une tache (valide par add_task)."""

    title: str
    due_on: date | None = None
    estimate_minutes: int | None = None
    priority: int = 2
    notes: str | None = None
    parent_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TaskView:
    id: uuid.UUID
    title: str
    notes: str | None
    status: str
    priority: int
    due_on: date | None
    estimate_minutes: int | None
    parent_id: uuid.UUID | None
    owner_module: str | None
    owner_ref: str | None
    source_kind: str
    created_at: datetime
    completed_at: datetime | None
    open_subtasks: int = 0

    def overdue(self, today: date) -> bool:
        """En retard : ouverte, et son jour d'echeance est passe (pas « aujourd'hui »)."""
        return self.status == "open" and self.due_on is not None and self.due_on < today


def _view(task: Task, open_subtasks: int = 0) -> TaskView:
    return TaskView(
        id=task.id,
        title=task.title,
        notes=task.notes,
        status=task.status,
        priority=task.priority,
        due_on=task.due_on,
        estimate_minutes=task.estimate_minutes,
        parent_id=task.parent_id,
        owner_module=task.owner_module,
        owner_ref=task.owner_ref,
        source_kind=task.source_kind,
        created_at=task.created_at,
        completed_at=task.completed_at,
        open_subtasks=open_subtasks,
    )


async def _open_subtasks(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Task.parent_id, func.count())
        .where(Task.parent_id.in_(ids), Task.status == "open")
        .group_by(Task.parent_id)
    )
    counts: dict[uuid.UUID, int] = {}
    for parent, count in rows:
        if parent is not None:
            counts[parent] = count
    return counts


# ----------------------------------------------------------------- lecture
async def list_tasks(
    session: AsyncSession, status: TaskStatus = "open", limit: int = 50
) -> list[TaskView]:
    """Taches de l'utilisateur : echeance la plus proche d'abord (sans echeance a la fin),
    puis priorite, puis anciennete ; les terminees, les plus recentes d'abord."""
    query = select(Task).where(Task.status == status)
    if status == "open":
        query = query.order_by(
            Task.due_on.asc().nulls_last(), Task.priority, Task.created_at, Task.id
        )
    else:
        query = query.order_by(Task.completed_at.desc(), Task.id)
    tasks = list(await session.scalars(query.limit(max(1, min(limit, MAX_LIST)))))
    counts = await _open_subtasks(session, [t.id for t in tasks])
    return [_view(t, counts.get(t.id, 0)) for t in tasks]


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> TaskView:
    task = await session.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    counts = await _open_subtasks(session, [task.id])
    return _view(task, counts.get(task.id, 0))


# --------------------------------------------------------------- ecriture
async def _check_room(session: AsyncSession, parent_id: uuid.UUID | None) -> None:
    opened = await session.scalar(
        select(func.count()).select_from(Task).where(Task.status == "open")
    )
    if (opened or 0) >= MAX_OPEN_TASKS:
        raise TaskLimitError(f"{MAX_OPEN_TASKS} taches ouvertes au plus")
    if parent_id is None:
        return
    parent = await session.get(Task, parent_id, with_for_update=True)
    if parent is None:
        raise TaskNotFoundError(parent_id)
    if parent.parent_id is not None:
        raise TaskStateError("une sous-tache ne peut pas avoir de sous-tache")
    if parent.status != "open":
        raise TaskStateError("la tache parente est deja terminee")
    children = await session.scalar(
        select(func.count()).select_from(Task).where(Task.parent_id == parent_id)
    )
    if (children or 0) >= MAX_SUBTASKS:
        raise TaskLimitError(f"{MAX_SUBTASKS} sous-taches au plus")


async def add_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    new: NewTask,
    *,
    source_kind: SourceKind = "user",
    source_ref: str | None = None,
    ip: str | None = None,
) -> TaskView:
    """Cree une tache personnelle (ou une sous-tache), apres validation et plafonds."""
    title = clean_line(new.title, MAX_TITLE_CHARS)
    notes = clean_notes(new.notes)
    _check_numbers(new.priority, new.estimate_minutes)
    await _check_room(session, new.parent_id)
    task = Task(
        id=uuid.uuid4(),
        user_id=user_id,
        parent_id=new.parent_id,
        title=title,
        notes=notes,
        priority=new.priority,
        due_on=new.due_on,
        estimate_minutes=new.estimate_minutes,
        source_kind=source_kind,
        source_ref=source_ref,
    )
    session.add(task)
    await session.flush()
    await session.refresh(task)
    await audit(session, user_id, "planning.task_add", "success", ip, {"task_id": str(task.id)})
    return _view(task)


async def complete_task(
    session: AsyncSession,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    now: datetime,
    ip: str | None = None,
) -> int:
    """Termine une tache et ses sous-taches encore ouvertes ; rend le nombre de taches closes."""
    task = await session.get(Task, task_id, with_for_update=True)
    if task is None:
        raise TaskNotFoundError(task_id)
    if task.status == "done":
        raise TaskStateError("tache deja terminee")
    result = await session.execute(
        update(Task)
        .where(or_(Task.id == task_id, Task.parent_id == task_id), Task.status == "open")
        .values(status="done", completed_at=now, updated_at=func.now())
        .returning(Task.id)
    )
    closed = len(result.all())
    await audit(
        session, user_id, "planning.task_complete", "success", ip, {"task_id": str(task_id)}
    )
    return closed


async def delete_task(
    session: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID, ip: str | None = None
) -> None:
    """Supprime une tache personnelle et ses sous-taches (cascade).

    Une tache creee par un module ne se supprime que par ce module : sinon le devoir ou le
    projet garderait une tache fantome.
    """
    task = await session.get(Task, task_id, with_for_update=True)
    if task is None:
        raise TaskNotFoundError(task_id)
    if task.owner_module is not None:
        raise TaskStateError(f"tache du module {task.owner_module}")
    await session.execute(delete(Task).where(Task.id == task_id))
    await audit(session, user_id, "planning.task_delete", "success", ip, {"task_id": str(task_id)})


# ------------------------------------------------------- port des modules
class ModuleTasks:
    """Taches d'UN module, reperees par sa reference (ex. l'identifiant d'un devoir).

    Chaque requete filtre sur `owner_module` : un module ne voit ni ne modifie les taches
    personnelles ni celles d'un autre module.
    """

    def __init__(self, module_id: str) -> None:
        if not MODULE_ID.fullmatch(module_id):
            raise ValueError(f"identifiant de module invalide : {module_id}")
        self.module_id = module_id

    def _mine(self, ref: str) -> list[ColumnElement[bool]]:
        return [Task.owner_module == self.module_id, Task.owner_ref == ref]

    async def get(self, session: AsyncSession, ref: str) -> TaskView | None:
        task = await session.scalar(select(Task).where(*self._mine(ref)))
        return _view(task) if task is not None else None

    async def upsert(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        ref: str,
        title: str,
        *,
        due_on: date | None = None,
        estimate_minutes: int | None = None,
        priority: int = 2,
        notes: str | None = None,
    ) -> TaskView:
        """Cree la tache de `ref`, ou met a jour son contenu (jamais son statut)."""
        ref = clean_line(ref, 200, "reference")
        title = clean_line(title, MAX_TITLE_CHARS)
        notes = clean_notes(notes)
        _check_numbers(priority, estimate_minutes)
        task = await session.scalar(select(Task).where(*self._mine(ref)).with_for_update())
        if task is None:
            await _check_room(session, None)
            task = Task(
                id=uuid.uuid4(),
                user_id=user_id,
                owner_module=self.module_id,
                owner_ref=ref,
                source_kind="module",
                source_ref=self.module_id,
            )
            session.add(task)
        task.title = title
        task.notes = notes
        task.due_on = due_on
        task.estimate_minutes = estimate_minutes
        task.priority = priority
        task.updated_at = datetime.now(UTC)
        await session.flush()
        await session.refresh(task)
        return _view(task)

    async def complete(self, session: AsyncSession, ref: str, now: datetime) -> bool:
        """Termine la tache de `ref` ; False si elle n'existe pas ou l'est deja."""
        result = await session.execute(
            update(Task)
            .where(*self._mine(ref), Task.status == "open")
            .values(status="done", completed_at=now, updated_at=func.now())
            .returning(Task.id)
        )
        return result.first() is not None

    async def delete(self, session: AsyncSession, ref: str) -> bool:
        result = await session.execute(delete(Task).where(*self._mine(ref)).returning(Task.id))
        return result.first() is not None


# ------------------------------------------------------------------ agenda
@dataclass(frozen=True)
class AgendaItem:
    """Creneau a ecrire : horaire (starts_at, ends_at aware) OU journee entiere (dates)."""

    external_key: str
    title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = None


@dataclass(frozen=True)
class AgendaView:
    id: uuid.UUID
    title: str
    location: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    start_date: date | None
    end_date: date | None
    owner_module: str | None

    @property
    def all_day(self) -> bool:
        return self.start_date is not None


def _check_item(item: AgendaItem) -> AgendaItem:
    try:
        title = clean_line(item.title, MAX_TITLE_CHARS)
        location = clean_line(item.location, MAX_LOCATION_CHARS, "lieu") if item.location else None
        key = clean_line(item.external_key, 300, "occurrence")
    except InvalidTaskError as error:
        raise InvalidAgendaEntryError(str(error)) from None
    timed = item.starts_at is not None or item.ends_at is not None
    dated = item.start_date is not None or item.end_date is not None
    if timed == dated:
        raise InvalidAgendaEntryError("creneau horaire OU journee entiere")
    if timed:
        if item.starts_at is None or item.ends_at is None:
            raise InvalidAgendaEntryError("debut et fin obligatoires")
        if item.starts_at.tzinfo is None or item.ends_at.tzinfo is None:
            raise InvalidAgendaEntryError("heures sans fuseau refusees")
        if item.ends_at <= item.starts_at:
            raise InvalidAgendaEntryError("la fin precede le debut")
    elif item.start_date is None or item.end_date is None or item.end_date <= item.start_date:
        raise InvalidAgendaEntryError("journee entiere : fin (exclue) apres le debut")
    return AgendaItem(
        key, title, item.starts_at, item.ends_at, item.start_date, item.end_date, location
    )


class ModuleAgenda:
    """Creneaux d'UN module, par source (ex. un abonnement ICS)."""

    def __init__(self, module_id: str) -> None:
        if not MODULE_ID.fullmatch(module_id):
            raise ValueError(f"identifiant de module invalide : {module_id}")
        self.module_id = module_id

    async def replace_source(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        source_key: str,
        items: Sequence[AgendaItem],
    ) -> int:
        """Remplace tous les creneaux de la source par `items` (idempotent : rejouer le meme
        envoi donne le meme agenda, sans doublon). Tout est valide avant d'ecrire."""
        try:
            source = clean_line(source_key, 100, "source")
        except InvalidTaskError as error:
            raise InvalidAgendaEntryError(str(error)) from None
        if len(items) > MAX_ENTRIES_PER_SOURCE:
            raise InvalidAgendaEntryError(f"{MAX_ENTRIES_PER_SOURCE} creneaux au plus par source")
        checked = [_check_item(i) for i in items]
        if len({i.external_key for i in checked}) != len(checked):
            raise InvalidAgendaEntryError("occurrence en double dans le meme envoi")
        await session.execute(
            delete(AgendaEntry).where(
                AgendaEntry.owner_module == self.module_id, AgendaEntry.source_key == source
            )
        )
        session.add_all(
            AgendaEntry(
                id=uuid.uuid4(),
                user_id=user_id,
                title=i.title,
                location=i.location,
                starts_at=i.starts_at,
                ends_at=i.ends_at,
                start_date=i.start_date,
                end_date=i.end_date,
                owner_module=self.module_id,
                source_key=source,
                external_key=i.external_key,
            )
            for i in checked
        )
        await session.flush()
        return len(checked)

    async def clear_source(self, session: AsyncSession, source_key: str) -> int:
        result = await session.execute(
            delete(AgendaEntry)
            .where(AgendaEntry.owner_module == self.module_id, AgendaEntry.source_key == source_key)
            .returning(AgendaEntry.id)
        )
        return len(result.all())


async def agenda_for_days(
    session: AsyncSession, first_day: date, days: int, tz: ZoneInfo
) -> list[AgendaView]:
    """Creneaux qui touchent les jours locaux [first_day, first_day + days[, par debut.

    Un creneau horaire est retenu s'il chevauche la periode (un cours de 23 h a 1 h compte
    pour les deux jours) ; une journee entiere, si ses dates la chevauchent.
    """
    last = first_day + timedelta(days=max(1, days))
    start, _ = day_bounds(first_day, tz)
    end, _ = day_bounds(last, tz)
    entries = await session.scalars(
        select(AgendaEntry).where(
            or_(
                and_(AgendaEntry.starts_at < end, AgendaEntry.ends_at > start),
                and_(AgendaEntry.start_date < last, AgendaEntry.end_date > first_day),
            )
        )
    )
    views = [
        AgendaView(
            e.id,
            e.title,
            e.location,
            e.starts_at,
            e.ends_at,
            e.start_date,
            e.end_date,
            e.owner_module,
        )
        for e in entries
    ]
    return sorted(views, key=lambda v: _sort_key(v, tz))


_EARLIEST: Final = datetime.min.replace(tzinfo=UTC)


def _sort_key(view: AgendaView, tz: ZoneInfo) -> tuple[date, int, datetime, str]:
    """Par jour local, les journees entieres d'abord, puis par heure de debut."""
    if view.start_date is not None or view.starts_at is None:
        return (view.start_date or date.min, 0, _EARLIEST, view.title)
    return (view.starts_at.astimezone(tz).date(), 1, view.starts_at, view.title)
