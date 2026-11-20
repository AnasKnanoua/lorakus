"""Routes du module academic, montees sous /api/v1/academic (PR 46).

Le Core ajoute la verification de session et d'activation du module. « Aujourd'hui », les
retards et le nombre de jours restants sont calcules ICI, dans le fuseau du compte : la page
n'a pas a deviner quel jour il est chez l'utilisateur.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from lorakus.api.auth import client_ip, current_user
from lorakus.core.account.clock import local_today
from lorakus.core.account.service import user_timezone
from lorakus.core.identity.service import CurrentUser
from lorakus.core.planning.service import MAX_ESTIMATE_MINUTES
from lorakus.db.database import Database
from lorakus_modules.academic.service import (
    MAX_COURSE_CHARS,
    MAX_TITLE_CHARS,
    AcademicError,
    AssessmentNotFoundError,
    AssessmentView,
    CourseNotFoundError,
    CourseView,
    NewAssessment,
    add_assessment,
    add_course,
    check_due,
    complete_assessment,
    delete_assessment,
    delete_course,
    list_assessments,
    list_courses,
    update_assessment,
)

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]
COURSE_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Cours introuvable.")
ASSESSMENT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Évaluation introuvable.")
Kind = Literal["assignment", "exam"]


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _refused(error: AcademicError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


class CourseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_COURSE_CHARS)


class CourseOut(BaseModel):
    id: uuid.UUID
    name: str
    open_assessments: int


class AssessmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind = "assignment"
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    due_on: date
    weight: float | None = Field(default=None, gt=0, le=100)
    estimate_minutes: int | None = Field(default=None, ge=1, le=MAX_ESTIMATE_MINUTES)

    def new(self) -> NewAssessment:
        weight = None if self.weight is None else Decimal(str(self.weight))
        return NewAssessment(self.kind, self.title, self.due_on, weight, self.estimate_minutes)


class AssessmentIn(AssessmentBody):
    course_id: uuid.UUID


class AssessmentOut(BaseModel):
    """Une evaluation, avec ce que le serveur sait du temps : retard et jours restants."""

    id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    kind: Kind
    title: str
    due_on: date
    weight: float | None
    estimate_minutes: int | None
    status: Literal["open", "done"]
    overdue: bool
    days_left: int
    completed_at: datetime | None


def _course(view: CourseView) -> CourseOut:
    return CourseOut(id=view.id, name=view.name, open_assessments=view.open_assessments)


def _assessment(view: AssessmentView, today: date) -> AssessmentOut:
    return AssessmentOut(
        id=view.id,
        course_id=view.course_id,
        course_name=view.course_name,
        kind=cast(Kind, view.kind),
        title=view.title,
        due_on=view.due_on,
        weight=None if view.weight is None else float(view.weight),
        estimate_minutes=view.estimate_minutes,
        status=cast(Literal["open", "done"], view.status),
        overdue=view.overdue(today),
        days_left=view.days_left(today),
        completed_at=view.completed_at,
    )


# ------------------------------------------------------------------ cours
@router.get("/courses")
async def get_courses(request: Request, user: User) -> list[CourseOut]:
    async with _database(request).transaction(user.id) as session:
        return [_course(c) for c in await list_courses(session)]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseIn, request: Request, user: User) -> CourseOut:
    try:
        async with _database(request).transaction(user.id) as session:
            return _course(await add_course(session, user.id, body.name, client_ip(request)))
    except AcademicError as error:
        raise _refused(error) from None


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_course(course_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            await delete_course(session, user.id, course_id, client_ip(request))
    except CourseNotFoundError:
        raise COURSE_NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ evaluations
@router.get("/assessments")
async def get_assessments(
    request: Request, user: User, state: Literal["open", "done"] = "open"
) -> list[AssessmentOut]:
    async with _database(request).transaction(user.id) as session:
        today = local_today(datetime.now(UTC), await user_timezone(session))
        return [_assessment(a, today) for a in await list_assessments(session, state)]


@router.post("/assessments", status_code=status.HTTP_201_CREATED)
async def create_assessment(body: AssessmentIn, request: Request, user: User) -> AssessmentOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(datetime.now(UTC), await user_timezone(session))
            check_due(body.due_on, today, allow_past=True)
            view = await add_assessment(
                session, user.id, body.course_id, body.new(), ip=client_ip(request)
            )
            return _assessment(view, today)
    except AcademicError as error:
        raise _refused(error) from None
    except CourseNotFoundError:
        raise COURSE_NOT_FOUND from None


@router.put("/assessments/{assessment_id}")
async def change_assessment(
    assessment_id: uuid.UUID, body: AssessmentBody, request: Request, user: User
) -> AssessmentOut:
    try:
        async with _database(request).transaction(user.id) as session:
            today = local_today(datetime.now(UTC), await user_timezone(session))
            check_due(body.due_on, today, allow_past=True)
            view = await update_assessment(
                session, user.id, assessment_id, body.new(), client_ip(request)
            )
            return _assessment(view, today)
    except AcademicError as error:
        raise _refused(error) from None
    except AssessmentNotFoundError:
        raise ASSESSMENT_NOT_FOUND from None


@router.post("/assessments/{assessment_id}/complete")
async def finish_assessment(
    assessment_id: uuid.UUID, request: Request, user: User
) -> AssessmentOut:
    try:
        async with _database(request).transaction(user.id) as session:
            now = datetime.now(UTC)
            today = local_today(now, await user_timezone(session))
            view = await complete_assessment(
                session, user.id, assessment_id, now, client_ip(request)
            )
            return _assessment(view, today)
    except AcademicError as error:
        raise _refused(error) from None
    except AssessmentNotFoundError:
        raise ASSESSMENT_NOT_FOUND from None


@router.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_assessment(assessment_id: uuid.UUID, request: Request, user: User) -> Response:
    try:
        async with _database(request).transaction(user.id) as session:
            await delete_assessment(session, user.id, assessment_id, client_ip(request))
    except AssessmentNotFoundError:
        raise ASSESSMENT_NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
