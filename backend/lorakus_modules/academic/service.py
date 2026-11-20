"""Cours et evaluations (PR 46), au-dessus du planning du Core (ADR 0018).

Le module garde le sens metier : un cours, un devoir ou un examen, un coefficient. Chaque
evaluation cree SA tache par le port `ModuleTasks` (`owner_ref` = identifiant de
l'evaluation) : c'est cette tache que voient la liste des taches, l'assistant et, plus tard,
le planificateur. Les deux restent d'accord dans les deux sens :

- terminer, modifier ou supprimer une evaluation ici met sa tache a jour dans la meme
  transaction ;
- terminer la tache ailleurs (chat) publie `planning.task_completed`, et `on_task_completed`
  termine l'evaluation (events.py).

Toutes les fonctions recoivent une session deja liee a l'utilisateur (RLS) et s'executent
dans la transaction de l'appelant : une carte de confirmation du chat cree l'evaluation et sa
tache dans la meme transaction que sa propre decision (ADR 0040, regle 7).

Aucun LLM, aucun appel reseau : des regles et PostgreSQL.
"""

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
from lorakus_modules.academic.models import Assessment, Course

MODULE_ID: Final = "academic"
TASKS: Final = ModuleTasks(MODULE_ID)

Kind = Literal["assignment", "exam"]
Status = Literal["open", "done"]

MAX_COURSES: Final = 50
MAX_OPEN_ASSESSMENTS: Final = 200
MAX_LIST: Final = 200
MAX_COURSE_CHARS: Final = 80
# Titre de la tache = « cours : titre » : 80 + 3 + 110 tiennent dans les 200 du planning.
MAX_TITLE_CHARS: Final = 110
MAX_WEIGHT: Final = Decimal(100)
# Une echeance plus lointaine (ou plus ancienne) est presque toujours une erreur de saisie.
MAX_DAYS_AHEAD: Final = 5 * 366
MAX_DAYS_BEHIND: Final = 366

KIND_LABEL: Final[dict[str, str]] = {"assignment": "Devoir", "exam": "Examen"}


class AcademicError(Exception):
    """Refus lisible par l'utilisateur (message en francais, tutoiement)."""


class DuplicateAssessmentError(AcademicError):
    """Une evaluation ouverte du meme cours porte deja ce titre et cette echeance."""

    def __init__(self) -> None:
        super().__init__("Cette évaluation existe déjà, avec la même échéance.")


class CourseNotFoundError(Exception):
    """Cours absent ou d'un autre utilisateur (la RLS les confond)."""


class AssessmentNotFoundError(Exception):
    """Evaluation absente ou d'un autre utilisateur (la RLS les confond)."""


@dataclass(frozen=True)
class CourseView:
    id: uuid.UUID
    name: str
    open_assessments: int
    created_at: datetime


@dataclass(frozen=True)
class NewAssessment:
    """Contenu d'une evaluation, a creer ou a corriger (valide par le service)."""

    kind: Kind
    title: str
    due_on: date
    weight: Decimal | None = None
    estimate_minutes: int | None = None


@dataclass(frozen=True)
class AssessmentView:
    id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    kind: str
    title: str
    due_on: date
    weight: Decimal | None
    estimate_minutes: int | None
    status: str
    created_at: datetime
    completed_at: datetime | None

    def overdue(self, today: date) -> bool:
        """En retard : ouverte, et son jour d'echeance est passe (pas « aujourd'hui »)."""
        return self.status == "open" and self.due_on < today

    def days_left(self, today: date) -> int:
        """Jours avant l'echeance (0 : aujourd'hui ; negatif : passee)."""
        return (self.due_on - today).days


# ------------------------------------------------------------- validation
def _line(text: str, limit: int, empty: str, too_long: str) -> str:
    """Une ligne visible (memes regles que les titres de taches), ou un refus lisible."""
    try:
        value = clean_line(text, max(limit, len(text)))
    except InvalidTaskError:
        raise AcademicError(empty) from None  # rien de visible
    if len(value) > limit:
        raise AcademicError(too_long)
    return value


def clean_course_name(name: str) -> str:
    return _line(
        name,
        MAX_COURSE_CHARS,
        "Donne un nom à ce cours.",
        f"Nom du cours trop long ({MAX_COURSE_CHARS} caractères au plus).",
    )


def clean_title(title: str) -> str:
    return _line(
        title,
        MAX_TITLE_CHARS,
        "Donne un titre à cette évaluation.",
        f"Titre trop long ({MAX_TITLE_CHARS} caractères au plus).",
    )


def course_key(name: str) -> str:
    """Cle de comparaison d'un nom de cours : sans casse, sans accents, espaces regroupes.

    « Réseaux », « reseaux » et « RÉSEAUX » designent le meme cours.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    key = " ".join(bare.casefold().split())
    if not key:
        raise AcademicError("Donne un nom à ce cours.")
    return key


def clean_weight(weight: Decimal | None) -> Decimal | None:
    """Coefficient : plus grand que 0, 100 au plus, deux decimales."""
    if weight is None:
        return None
    try:
        value = weight.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise AcademicError("Coefficient invalide.") from None
    if not value.is_finite() or value <= 0 or value > MAX_WEIGHT:
        raise AcademicError("Le coefficient doit être plus grand que 0, et de 100 au plus.")
    return value


def check_due(due_on: date, today: date, *, allow_past: bool) -> None:
    """Echeance plausible. Le chat refuse toute date passee (erreur du modele probable) ; la
    page accepte un devoir deja en retard, saisi par l'utilisateur lui-meme."""
    if due_on < today and not allow_past:
        raise AcademicError("Cette échéance est déjà passée : vérifie le jour voulu.")
    if due_on < today - timedelta(days=MAX_DAYS_BEHIND):
        raise AcademicError("Échéance trop ancienne : vérifie l'année.")
    if due_on > today + timedelta(days=MAX_DAYS_AHEAD):
        raise AcademicError("Échéance trop lointaine : vérifie l'année.")


def _checked(new: NewAssessment) -> NewAssessment:
    if new.kind not in KIND_LABEL:
        raise AcademicError("Type d'évaluation inconnu.")
    if new.estimate_minutes is not None and not 1 <= new.estimate_minutes <= MAX_ESTIMATE_MINUTES:
        raise AcademicError("Durée estimée invalide.")
    return NewAssessment(
        kind=new.kind,
        title=clean_title(new.title),
        due_on=new.due_on,
        weight=clean_weight(new.weight),
        estimate_minutes=new.estimate_minutes,
    )


def task_title(course_name: str, title: str) -> str:
    """Titre de la tache du planning : « Machine Learning : Devoir 2 »."""
    return f"{course_name} : {title}"


def _view(row: Assessment, course_name: str) -> AssessmentView:
    return AssessmentView(
        id=row.id,
        course_id=row.course_id,
        course_name=course_name,
        kind=row.kind,
        title=row.title,
        due_on=row.due_on,
        weight=row.weight,
        estimate_minutes=row.estimate_minutes,
        status=row.status,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


# ------------------------------------------------------------------ cours
async def list_courses(session: AsyncSession) -> list[CourseView]:
    """Cours par ordre alphabetique, avec leur nombre d'evaluations encore ouvertes."""
    opened = (
        select(Assessment.course_id, func.count().label("n"))
        .where(Assessment.status == "open")
        .group_by(Assessment.course_id)
        .subquery()
    )
    rows = await session.execute(
        select(Course, func.coalesce(opened.c.n, 0))
        .outerjoin(opened, opened.c.course_id == Course.id)
        .order_by(Course.name_key, Course.id)
    )
    return [CourseView(c.id, c.name, n, c.created_at) for c, n in rows]


async def find_course(session: AsyncSession, name: str) -> CourseView | None:
    """Cours de ce nom (sans casse ni accents), ou None."""
    key = course_key(clean_course_name(name))
    course = await session.scalar(select(Course).where(Course.name_key == key))
    return None if course is None else CourseView(course.id, course.name, 0, course.created_at)


async def add_course(
    session: AsyncSession, user_id: uuid.UUID, name: str, ip: str | None = None
) -> CourseView:
    clean = clean_course_name(name)
    key = course_key(clean)
    if await session.scalar(select(Course.id).where(Course.name_key == key)) is not None:
        raise AcademicError("Tu as déjà un cours de ce nom.")
    count = await session.scalar(select(func.count()).select_from(Course))
    if (count or 0) >= MAX_COURSES:
        raise AcademicError(f"{MAX_COURSES} cours au plus : supprime-en un avant d'en ajouter.")
    course = Course(id=uuid.uuid4(), user_id=user_id, name=clean, name_key=key)
    session.add(course)
    await session.flush()
    await session.refresh(course)
    await audit(
        session, user_id, "academic.course_add", "success", ip, {"course_id": str(course.id)}
    )
    return CourseView(course.id, course.name, 0, course.created_at)


async def delete_course(
    session: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID, ip: str | None = None
) -> int:
    """Supprime un cours, ses evaluations et leurs taches ; rend le nombre d'evaluations."""
    course = await session.get(Course, course_id, with_for_update=True)
    if course is None:
        raise CourseNotFoundError(course_id)
    ids = list(
        await session.scalars(select(Assessment.id).where(Assessment.course_id == course.id))
    )
    for assessment_id in ids:
        await TASKS.delete(session, str(assessment_id))
    await session.execute(delete(Course).where(Course.id == course.id))  # cascade
    await audit(
        session,
        user_id,
        "academic.course_delete",
        "success",
        ip,
        {"course_id": str(course_id), "assessments": len(ids)},
    )
    return len(ids)


# ------------------------------------------------------------ evaluations
async def list_assessments(
    session: AsyncSession, status: Status = "open", limit: int = MAX_LIST
) -> list[AssessmentView]:
    """Ouvertes : echeance la plus proche d'abord ; terminees : les plus recentes d'abord."""
    query = (
        select(Assessment, Course.name)
        .join(Course, Course.id == Assessment.course_id)
        .where(Assessment.status == status)
    )
    if status == "open":
        query = query.order_by(Assessment.due_on, Assessment.created_at, Assessment.id)
    else:
        query = query.order_by(Assessment.completed_at.desc(), Assessment.id)
    rows = await session.execute(query.limit(max(1, min(limit, MAX_LIST))))
    return [_view(row, name) for row, name in rows]


async def find_open_duplicate(
    session: AsyncSession,
    course_id: uuid.UUID,
    title: str,
    due_on: date,
    *,
    except_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Evaluation ouverte du meme cours, de meme titre (casse ignoree) et de meme echeance."""
    query = select(Assessment.id).where(
        Assessment.course_id == course_id,
        Assessment.status == "open",
        Assessment.due_on == due_on,
        func.lower(Assessment.title) == func.lower(clean_title(title)),
    )
    if except_id is not None:
        query = query.where(Assessment.id != except_id)
    return await session.scalar(query.limit(1))


async def _sync_task(session: AsyncSession, row: Assessment, course_name: str) -> None:
    try:
        await TASKS.upsert(
            session,
            row.user_id,
            str(row.id),
            task_title(course_name, row.title),
            due_on=row.due_on,
            estimate_minutes=row.estimate_minutes,
        )
    except TaskLimitError:
        raise AcademicError(
            "Tu as trop de tâches ouvertes : termines-en avant d'ajouter une évaluation."
        ) from None


async def add_assessment(
    session: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    new: NewAssessment,
    *,
    source_ref: str | None = None,
    ip: str | None = None,
) -> AssessmentView:
    """Cree une evaluation et sa tache. Jamais deux evaluations ouvertes identiques."""
    checked = _checked(new)
    course = await session.get(Course, course_id, with_for_update=True)
    if course is None:
        raise CourseNotFoundError(course_id)
    opened = await session.scalar(
        select(func.count()).select_from(Assessment).where(Assessment.status == "open")
    )
    if (opened or 0) >= MAX_OPEN_ASSESSMENTS:
        raise AcademicError(f"{MAX_OPEN_ASSESSMENTS} évaluations ouvertes au plus.")
    if await find_open_duplicate(session, course.id, checked.title, checked.due_on) is not None:
        raise DuplicateAssessmentError
    row = Assessment(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=course.id,
        kind=checked.kind,
        title=checked.title,
        due_on=checked.due_on,
        weight=checked.weight,
        estimate_minutes=checked.estimate_minutes,
        source_kind="conversation" if source_ref else "user",
        source_ref=source_ref,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await _sync_task(session, row, course.name)
    await audit(
        session, user_id, "academic.assessment_add", "success", ip, {"assessment_id": str(row.id)}
    )
    return _view(row, course.name)


async def _locked(session: AsyncSession, assessment_id: uuid.UUID) -> tuple[Assessment, str]:
    row = await session.get(Assessment, assessment_id, with_for_update=True)
    if row is None:
        raise AssessmentNotFoundError(assessment_id)
    name = await session.scalar(select(Course.name).where(Course.id == row.course_id))
    return row, name or ""


async def update_assessment(
    session: AsyncSession,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    new: NewAssessment,
    ip: str | None = None,
) -> AssessmentView:
    """Corrige une evaluation ouverte ; sa tache suit (titre, echeance, duree)."""
    checked = _checked(new)
    row, course_name = await _locked(session, assessment_id)
    if row.status != "open":
        raise AcademicError("Cette évaluation est déjà terminée.")
    duplicate = await find_open_duplicate(
        session, row.course_id, checked.title, checked.due_on, except_id=row.id
    )
    if duplicate is not None:
        raise DuplicateAssessmentError
    row.kind = checked.kind
    row.title = checked.title
    row.due_on = checked.due_on
    row.weight = checked.weight
    row.estimate_minutes = checked.estimate_minutes
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    await _sync_task(session, row, course_name)
    await audit(
        session,
        user_id,
        "academic.assessment_update",
        "success",
        ip,
        {"assessment_id": str(row.id)},
    )
    return _view(row, course_name)


async def complete_assessment(
    session: AsyncSession,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    now: datetime,
    ip: str | None = None,
) -> AssessmentView:
    """Termine une evaluation et sa tache (par le port : aucun evenement en retour)."""
    row, course_name = await _locked(session, assessment_id)
    if row.status != "open":
        raise AcademicError("Cette évaluation est déjà terminée.")
    row.status = "done"
    row.completed_at = now
    row.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    await TASKS.complete(session, str(row.id), now)
    await audit(
        session,
        user_id,
        "academic.assessment_complete",
        "success",
        ip,
        {"assessment_id": str(row.id)},
    )
    return _view(row, course_name)


async def delete_assessment(
    session: AsyncSession, user_id: uuid.UUID, assessment_id: uuid.UUID, ip: str | None = None
) -> None:
    """Supprime une evaluation et sa tache."""
    row, _ = await _locked(session, assessment_id)
    await TASKS.delete(session, str(row.id))
    await session.execute(delete(Assessment).where(Assessment.id == row.id))
    await audit(
        session,
        user_id,
        "academic.assessment_delete",
        "success",
        ip,
        {"assessment_id": str(assessment_id)},
    )


async def on_task_completed(session: AsyncSession, owner_ref: str) -> bool:
    """L'utilisateur a termine la tache d'une evaluation : l'evaluation l'est aussi.

    L'evenement n'est qu'un signal : l'etat est relu dans le planning (la tache doit exister,
    etre a ce module et etre terminee). Rejouable sans effet (livraison au moins une fois) ;
    rend True si une evaluation vient d'etre terminee.
    """
    try:
        assessment_id = uuid.UUID(owner_ref)
    except ValueError:
        return False
    task = await TASKS.get(session, str(assessment_id))
    if task is None or task.status != "done" or task.completed_at is None:
        return False
    row = await session.get(Assessment, assessment_id, with_for_update=True)
    if row is None or row.status != "open":
        return False
    row.status = "done"
    row.completed_at = task.completed_at
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return True
