"""Outil du chat du module academic (PR 46, ADR 0040) : proposer un devoir ou un examen.

L'outil est `write` : il ne fait rien de lui-meme. Le ToolRuntime affiche une carte dont le
TEXTE est ecrit ici, a partir des arguments valides et des donnees de l'utilisateur, jamais
par le modele. La carte donne l'echeance en date ABSOLUE, calculee dans le fuseau du compte :
si le modele a mal compris « vendredi », l'utilisateur le voit avant de confirmer. Elle dit
aussi quand le cours n'existe pas encore (« nouveau cours ») : une faute dans le nom d'un
cours se voit avant le clic.

Refuses avant toute carte : une date passee ou trop lointaine, une evaluation ouverte
identique (meme cours, meme titre, meme echeance), un cours de trop.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from lorakus.core.account.clock import local_today
from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.planning.service import MAX_ESTIMATE_MINUTES
from lorakus.core.tools.spec import ToolCall, ToolError, ToolSpec
from lorakus_modules.academic.models import Course
from lorakus_modules.academic.service import (
    MAX_COURSE_CHARS,
    MAX_COURSES,
    MAX_TITLE_CHARS,
    AcademicError,
    CourseNotFoundError,
    NewAssessment,
    add_assessment,
    add_course,
    check_due,
    clean_course_name,
    clean_title,
    clean_weight,
    find_course,
    find_open_duplicate,
)

KindFr = Literal["devoir", "examen"]
KIND: Final[dict[str, Literal["assignment", "exam"]]] = {"devoir": "assignment", "examen": "exam"}
DEFAULT_TITLE: Final[dict[str, str]] = {"devoir": "Devoir", "examen": "Examen"}


class AddAssessmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course: str = Field(
        min_length=1,
        max_length=MAX_COURSE_CHARS,
        description="Nom du cours, tel que l'utilisateur le dit (ex. « Machine Learning »).",
    )
    kind: KindFr = Field(
        default="devoir", description="« devoir » (travail à rendre) ou « examen »."
    )
    due_on: date = Field(
        description="Échéance du devoir ou jour de l'examen, date exacte AAAA-MM-JJ calculée "
        "depuis la date du jour donnée plus haut. Obligatoire : si l'utilisateur ne la donne "
        "pas, demande-la au lieu d'en inventer une.",
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description="Intitulé court, sans le nom du cours (ex. « TP 2 », « Partiel ») ; "
        "absent si l'utilisateur n'en donne pas.",
    )
    estimate_minutes: int | None = Field(
        default=None,
        ge=1,
        le=MAX_ESTIMATE_MINUTES,
        description="Durée de travail estimée en minutes : celle que l'utilisateur donne, ou "
        "ton estimation s'il te la demande (alors estimate_by = lorakus).",
    )
    estimate_by: Literal["utilisateur", "lorakus"] = Field(
        default="utilisateur",
        description="Qui donne la durée : l'utilisateur, ou toi (lorakus) quand c'est ton "
        "estimation. La carte l'affiche.",
    )
    weight: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Coefficient, seulement si l'utilisateur le donne.",
    )


def _weight(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _new(args: AddAssessmentIn) -> NewAssessment:
    return NewAssessment(
        kind=KIND[args.kind],
        title=args.title or DEFAULT_TITLE[args.kind],
        due_on=args.due_on,
        weight=_weight(args.weight),
        estimate_minutes=args.estimate_minutes,
    )


def format_weight(weight: Decimal) -> str:
    """« 2 », « 0,5 », « 1,25 » : virgule francaise, sans zero inutile."""
    text = f"{weight:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


async def _add_summary(call: ToolCall, args: AddAssessmentIn) -> str:
    today = local_today(call.ports.clock(), await user_timezone(call.session))
    new = _new(args)
    try:
        course_name = clean_course_name(args.course)
        title = clean_title(new.title)
        weight = clean_weight(new.weight)
        check_due(new.due_on, today, allow_past=False)
        course = await find_course(call.session, course_name)
        if course is None:
            count = await call.session.scalar(select(func.count()).select_from(Course))
            if (count or 0) >= MAX_COURSES:
                raise AcademicError(f"{MAX_COURSES} cours au plus : supprime-en un d'abord.")
        # Avant toute carte : une evaluation deja ouverte et identique n'en montre pas.
        elif await find_open_duplicate(call.session, course.id, title, new.due_on) is not None:
            raise AcademicError("Cette évaluation est déjà dans tes cours, avec la même échéance.")
    except AcademicError as error:
        raise ToolError(str(error)) from None
    what = "un examen" if args.kind == "examen" else "un devoir"
    when = "Date" if args.kind == "examen" else "Échéance"
    lines = [
        f"Ajouter {what} : « {title} »",
        f"Cours : {course.name}" if course else f"Cours : {course_name} (nouveau cours)",
        f"{when} : {french_date(new.due_on)} ({relative_day(new.due_on, today)})",
    ]
    if new.estimate_minutes is not None:
        by = " (estimation de Lorakus)" if args.estimate_by == "lorakus" else ""
        lines.append(f"Durée estimée : {duration(new.estimate_minutes)}{by}")
    if weight is not None:
        lines.append(f"Coefficient : {format_weight(weight)}")
    return "\n".join(lines)


async def _add(call: ToolCall, args: AddAssessmentIn) -> dict[str, Any]:
    """Apres le clic : cree le cours s'il manque, puis l'evaluation et sa tache."""
    try:
        course = await find_course(call.session, args.course)
        course_id: uuid.UUID = (
            course.id
            if course is not None
            else (await add_course(call.session, call.user_id, args.course)).id
        )
        created = await add_assessment(
            call.session,
            call.user_id,
            course_id,
            _new(args),
            source_ref=call.origin,
            estimate_source="assistant" if args.estimate_by == "lorakus" else "user",
        )
    except AcademicError as error:
        raise ToolError(str(error)) from None
    except CourseNotFoundError:
        raise ToolError("Ce cours n'existe plus.") from None
    return {"message": "Évaluation ajoutée.", "id": str(created.id)}


TOOLS: Final = [
    ToolSpec(
        "academic.add_assessment",
        "Propose d'ajouter un devoir ou un examen d'un cours (à préférer à une tâche simple "
        "dès qu'il s'agit d'un travail à rendre ou d'un examen lié à un cours). Une carte "
        "s'affiche avec la date exacte : rien n'est enregistré tant que l'utilisateur ne l'a "
        "pas confirmée.",
        "write",
        AddAssessmentIn,
        _add,
        summary=_add_summary,
    ),
]
