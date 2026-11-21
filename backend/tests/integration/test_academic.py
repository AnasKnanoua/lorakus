"""Module academic (PR 46) : cours, evaluations, leur tache et l'evenement du planning.

Tout s'execute en lorakus_app, sous la RLS : un test qui passerait en proprietaire des
tables ne prouverait rien.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import migrator_sql
from sqlalchemy import text
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

from lorakus.core.events.bus import bus, publish
from lorakus.core.events.relay import OutboxRelay
from lorakus.core.identity.service import IdentityService
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.planning.service import (
    TASK_COMPLETED,
    TASK_ESTIMATED,
    ModuleTasks,
    NewTask,
    add_task,
    complete_task,
    get_task,
    list_tasks,
    set_estimate,
)
from lorakus.db.database import Database
from lorakus_modules.academic import service as academic
from lorakus_modules.academic.service import (
    AcademicError,
    AssessmentNotFoundError,
    CourseNotFoundError,
    DuplicateAssessmentError,
    NewAssessment,
    add_assessment,
    add_course,
    check_due,
    complete_assessment,
    course_key,
    delete_assessment,
    delete_course,
    find_course,
    list_assessments,
    list_courses,
    update_assessment,
)
from lorakus_modules.academic.tools import format_weight

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
TODAY = date(2026, 11, 18)
FRIDAY = date(2026, 11, 20)
TASKS = ModuleTasks("academic")
# Comme le worker au demarrage : decouvrir les modules abonne leurs handlers (@on).
ModuleRegistry.from_entry_points()


def test_discovering_the_modules_subscribes_the_handler() -> None:
    assert list(bus.handlers_for(TASK_COMPLETED)) == ["academic.task_completed"]
    assert list(bus.handlers_for(TASK_ESTIMATED)) == ["academic.task_estimated"]


async def _owner(identity: IdentityService) -> uuid.UUID:
    return await identity.create_owner("a@example.com", PASSWORD)


async def _second() -> uuid.UUID:
    other = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": other},
    )
    return other


def _homework(title: str = "TP 2", due_on: date = FRIDAY, **more: object) -> NewAssessment:
    return NewAssessment("assignment", title, due_on, **more)  # type: ignore[arg-type]


async def _events() -> list[tuple[object, ...]]:
    return await migrator_sql(
        "SELECT event_type, payload, published_at IS NOT NULL FROM lorakus.core_outbox ORDER BY id"
    )


# ------------------------------------------------------------------ cours
async def test_course_names_are_compared_without_case_or_accents(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        created = await add_course(session, user, "  Réseaux​  et\tsécurité ")
        assert created.name == "Réseaux et sécurité"  # une ligne, sans caractere invisible
        for same in ("reseaux et securite", "RÉSEAUX ET SÉCURITÉ", "Réseaux  et sécurité"):
            with pytest.raises(AcademicError, match="déjà un cours"):
                await add_course(session, user, same)
            found = await find_course(session, same)
            assert found is not None and found.id == created.id
        assert await find_course(session, "Réseaux") is None
        await add_course(session, user, "Algèbre")
        assert [c.name for c in await list_courses(session)] == ["Algèbre", "Réseaux et sécurité"]


@pytest.mark.parametrize(
    ("name", "message"),
    [("   ", "Donne un nom"), ("​", "Donne un nom"), ("x" * 81, "trop long"), ("́", "nom")],
)
async def test_bad_course_names_are_refused(
    database: Database, identity: IdentityService, name: str, message: str
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        with pytest.raises(AcademicError, match=message):
            await add_course(session, user, name)
        assert await list_courses(session) == []


def test_course_key_folds_case_accents_and_spaces() -> None:
    assert course_key("Réseaux  ET Sécurité") == "reseaux et securite"
    assert course_key("Straße") == "strasse"
    assert course_key("ML") != course_key("Machine Learning")


async def test_courses_are_limited(
    database: Database, identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _owner(identity)
    monkeypatch.setattr(academic, "MAX_COURSES", 2)
    async with database.transaction(user) as session:
        await add_course(session, user, "A1")
        await add_course(session, user, "B2")
        with pytest.raises(AcademicError, match="2 cours au plus"):
            await add_course(session, user, "C3")


# ------------------------------------------- une evaluation cree sa tache
async def test_an_assessment_creates_its_task_through_the_port(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Machine Learning")
        created = await add_assessment(
            session,
            user,
            course.id,
            NewAssessment("exam", " Partiel ", FRIDAY, Decimal("2.505"), 180),
            source_ref="conversation:abc",
        )
        assert (created.kind, created.title, created.course_name) == (
            "exam",
            "Partiel",
            "Machine Learning",
        )
        assert created.weight == Decimal("2.51")  # deux decimales, arrondi au plus proche
        task = await TASKS.get(session, str(created.id))
        assert task is not None
        assert task.title == "Machine Learning : Partiel"
        assert (task.due_on, task.estimate_minutes, task.status) == (FRIDAY, 180, "open")
        assert (task.owner_module, task.owner_ref) == ("academic", str(created.id))
        # La tache est celle que voit l'utilisateur dans sa liste.
        assert [t.id for t in await list_tasks(session)] == [task.id]
        assert [c.open_assessments for c in await list_courses(session)] == [1]
    rows = await migrator_sql(
        "SELECT source_kind, source_ref FROM lorakus.acad_assessments WHERE id = :id",
        {"id": created.id},
    )
    assert rows == [("conversation", "conversation:abc")]


@pytest.mark.parametrize(
    ("new", "message"),
    [
        (NewAssessment("assignment", "  ", FRIDAY), "Donne un titre"),
        (NewAssessment("assignment", "x" * 111, FRIDAY), "Titre trop long"),
        (NewAssessment("assignment", "TP", FRIDAY, Decimal(0)), "coefficient"),
        (NewAssessment("assignment", "TP", FRIDAY, Decimal("100.01")), "coefficient"),
        (NewAssessment("assignment", "TP", FRIDAY, Decimal("NaN")), "[Cc]oefficient"),
        (NewAssessment("assignment", "TP", FRIDAY, None, 0), "Durée"),
        (NewAssessment("assignment", "TP", FRIDAY, None, 10081), "Durée"),
        (NewAssessment("quiz", "TP", FRIDAY), "Type"),  # type: ignore[arg-type]
    ],
)
async def test_bad_assessments_are_refused_and_leave_no_task(
    database: Database, identity: IdentityService, new: NewAssessment, message: str
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        with pytest.raises(AcademicError, match=message):
            await add_assessment(session, user, course.id, new)
        assert await list_assessments(session) == []
        assert await list_tasks(session) == []


async def test_weight_bounds_are_accepted_at_the_edges(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        low = await add_assessment(session, user, course.id, _homework("a", weight=Decimal("0.01")))
        top = await add_assessment(session, user, course.id, _homework("b", weight=Decimal(100)))
        assert (low.weight, top.weight) == (Decimal("0.01"), Decimal(100))
        edge = await add_assessment(
            session, user, course.id, _homework("c", estimate_minutes=10080)
        )
        assert edge.estimate_minutes == 10080


def test_weights_are_written_the_french_way() -> None:
    assert [format_weight(Decimal(v)) for v in ("2.00", "0.50", "1.25", "100", "10.00")] == [
        "2",
        "0,5",
        "1,25",
        "100",
        "10",
    ]


async def test_two_identical_open_assessments_never_coexist(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        ml = await add_course(session, user, "Machine Learning")
        algo = await add_course(session, user, "Algo")
        first = await add_assessment(session, user, ml.id, _homework("TP 2"))
        with pytest.raises(DuplicateAssessmentError):
            await add_assessment(session, user, ml.id, _homework("tp 2"))
        # Autre cours, autre jour ou autre titre : ce n'est pas la meme evaluation.
        await add_assessment(session, user, algo.id, _homework("TP 2"))
        await add_assessment(session, user, ml.id, _homework("TP 2", FRIDAY + timedelta(days=7)))
        await add_assessment(session, user, ml.id, _homework("TP 3"))
        # Une fois terminee, la meme peut revenir (devoir hebdomadaire).
        await complete_assessment(session, user, first.id, NOW)
        await add_assessment(session, user, ml.id, _homework("TP 2"))
        assert len(await list_tasks(session)) == 4


async def test_open_assessments_are_limited(
    database: Database, identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _owner(identity)
    monkeypatch.setattr(academic, "MAX_OPEN_ASSESSMENTS", 2)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        first = await add_assessment(session, user, course.id, _homework("a"))
        await add_assessment(session, user, course.id, _homework("b"))
        with pytest.raises(AcademicError, match="2 évaluations ouvertes"):
            await add_assessment(session, user, course.id, _homework("c"))
        await complete_assessment(session, user, first.id, NOW)  # seules les ouvertes comptent
        await add_assessment(session, user, course.id, _homework("c"))


async def test_too_many_open_tasks_refuse_the_assessment_in_plain_words(
    database: Database, identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lorakus.core.planning import service as planning

    user = await _owner(identity)
    monkeypatch.setattr(planning, "MAX_OPEN_TASKS", 1)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        await add_task(session, user, NewTask("Faire les courses"))
    with pytest.raises(AcademicError, match="trop de tâches"):
        async with database.transaction(user) as session:
            await add_assessment(session, user, course.id, _homework())
    async with database.transaction(user) as session:
        assert await list_assessments(session) == []  # rien d'ecrit a moitie


# --------------------------------------------------- corriger, retards
async def test_updating_an_assessment_updates_its_task(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    later = FRIDAY + timedelta(days=3)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework("TP 2"))
        other = await add_assessment(session, user, course.id, _homework("TP 3", later))
        changed = await update_assessment(
            session, user, created.id, NewAssessment("exam", "Partiel", later, Decimal(3), 90)
        )
        assert (changed.kind, changed.title, changed.due_on) == ("exam", "Partiel", later)
        assert (changed.weight, changed.estimate_minutes) == (Decimal(3), 90)
        task = await TASKS.get(session, str(created.id))
        assert task is not None
        assert (task.title, task.due_on, task.estimate_minutes) == ("Algo : Partiel", later, 90)
        # Se corriger soi-meme sans rien changer n'est pas un doublon ; devenir une autre, si.
        await update_assessment(session, user, created.id, NewAssessment("exam", "Partiel", later))
        with pytest.raises(DuplicateAssessmentError):
            await update_assessment(session, user, created.id, _homework("tp 3", later))
        with pytest.raises(AssessmentNotFoundError):
            await update_assessment(session, user, uuid.uuid4(), _homework())
        await complete_assessment(session, user, other.id, NOW)
        with pytest.raises(AcademicError, match="déjà terminée"):
            await update_assessment(session, user, other.id, _homework("Autre", later))


async def test_overdue_means_the_due_day_is_over(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        for title, due in (
            ("hier", TODAY - timedelta(days=1)),
            ("ce soir", TODAY),
            ("vendredi", FRIDAY),
        ):
            await add_assessment(session, user, course.id, _homework(title, due))
        views = await list_assessments(session)
        assert [(v.title, v.overdue(TODAY), v.days_left(TODAY)) for v in views] == [
            ("hier", True, -1),
            ("ce soir", False, 0),  # a rendre aujourd'hui : pas encore en retard
            ("vendredi", False, 2),
        ]
        await complete_assessment(session, user, views[0].id, NOW)
        [done] = await list_assessments(session, "done")
        assert done.overdue(TODAY) is False  # terminee : plus jamais en retard


def test_due_dates_must_be_plausible() -> None:
    check_due(TODAY, TODAY, allow_past=False)
    check_due(TODAY - timedelta(days=1), TODAY, allow_past=True)  # devoir deja en retard
    check_due(TODAY - timedelta(days=366), TODAY, allow_past=True)
    check_due(TODAY + timedelta(days=5 * 366), TODAY, allow_past=False)
    with pytest.raises(AcademicError, match="déjà passée"):
        check_due(TODAY - timedelta(days=1), TODAY, allow_past=False)
    with pytest.raises(AcademicError, match="trop ancienne"):
        check_due(TODAY - timedelta(days=367), TODAY, allow_past=True)
    with pytest.raises(AcademicError, match="trop lointaine"):
        check_due(TODAY + timedelta(days=5 * 366 + 1), TODAY, allow_past=True)


# ------------------------------------------ terminer, dans les deux sens
async def test_completing_an_assessment_completes_its_task_without_event(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework())
        done = await complete_assessment(session, user, created.id, NOW)
        assert (done.status, done.completed_at) == ("done", NOW)
        task = await TASKS.get(session, str(created.id))
        assert task is not None and (task.status, task.completed_at) == ("done", NOW)
        with pytest.raises(AcademicError, match="déjà terminée"):
            await complete_assessment(session, user, created.id, NOW)
        with pytest.raises(AssessmentNotFoundError):
            await complete_assessment(session, user, uuid.uuid4(), NOW)
    assert await _events() == []  # le module le sait deja : aucun evenement en retour


async def test_completing_the_task_completes_the_assessment_through_the_event(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Machine Learning")
        created = await add_assessment(session, user, course.id, _homework())
        untouched = await add_assessment(session, user, course.id, _homework("TP 3"))
        task = await TASKS.get(session, str(created.id))
        assert task is not None
        # L'utilisateur termine la TACHE (comme le fait la carte du chat).
        assert await complete_task(session, user, task.id, NOW) == 1
        # Rien d'autre n'a encore bouge : c'est l'evenement qui previent le module.
        assert {a.id for a in await list_assessments(session)} == {created.id, untouched.id}
    payload = {"task_id": str(task.id), "owner_module": "academic", "owner_ref": str(created.id)}
    assert await _events() == [(TASK_COMPLETED, payload, False)]

    stats = await OutboxRelay(database, bus).run_once()

    assert (stats.delivered, stats.failed) == (1, 0)
    async with database.transaction(user) as session:
        assert [a.id for a in await list_assessments(session)] == [untouched.id]
        [done] = await list_assessments(session, "done")
        assert (done.id, done.status, done.completed_at) == (created.id, "done", NOW)
    assert await _events() == [(TASK_COMPLETED, payload, True)]
    handlers = await migrator_sql("SELECT handler FROM lorakus.core_outbox_deliveries")
    assert handlers == [("academic.task_completed",)]


async def test_a_personal_task_publishes_no_event(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        task = await add_task(session, user, NewTask("Faire les courses"))
        await complete_task(session, user, task.id, NOW)
    assert await _events() == []


async def test_the_event_is_only_a_signal_the_task_is_read_again(
    database: Database, identity: IdentityService
) -> None:
    """Un evenement faux, rejoue ou d'un autre module ne termine rien a tort."""
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework())
        ref = str(created.id)
        # Tache d'un autre module, avec la MEME reference : academic ne doit pas la suivre.
        await ModuleTasks("projects").upsert(session, user, ref, "Tache d'un projet")
        for payload in (
            {"owner_module": "academic", "owner_ref": ref},  # la tache n'est pas terminee
            {"owner_module": "projects", "owner_ref": ref},
            {"owner_module": "academic", "owner_ref": "pas-un-identifiant"},
            {"owner_module": "academic", "owner_ref": str(uuid.uuid4())},
            {"owner_module": "academic", "owner_ref": 12},
            {"owner_module": "academic"},
            {},
        ):
            await publish(session, TASK_COMPLETED, payload, user_id=user)
        await ModuleTasks("projects").complete(session, ref, NOW)

    stats = await OutboxRelay(database, bus).run_once()

    assert (stats.delivered, stats.failed) == (7, 0)
    async with database.transaction(user) as session:
        assert [a.status for a in await list_assessments(session)] == ["open"]
        # Vraie fin, puis le meme evenement livre deux fois : sans effet la seconde fois.
        task = await TASKS.get(session, ref)
        assert task is not None
        await complete_task(session, user, task.id, NOW)
        assert await academic.on_task_completed(session, ref) is True
        assert await academic.on_task_completed(session, ref) is False
        [done] = await list_assessments(session, "done")
        assert done.completed_at == NOW


async def test_the_event_of_one_user_never_touches_another(
    database: Database, identity: IdentityService
) -> None:
    user, other = await _owner(identity), await _second()
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework())
        await TASKS.complete(session, str(created.id), NOW)  # tache terminee, sans evenement
    # L'autre utilisateur publie un evenement qui vise l'evaluation du premier.
    async with database.transaction(other) as session:
        payload = {"owner_module": "academic", "owner_ref": str(created.id)}
        await publish(session, TASK_COMPLETED, payload, user_id=other)

    assert (await OutboxRelay(database, bus).run_once()).delivered == 1

    async with database.transaction(user) as session:
        assert [a.status for a in await list_assessments(session)] == ["open"]


# ------------------------------------------------- duree et temps (PR 49)
async def test_an_estimate_given_on_the_task_reaches_the_assessment(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Machine Learning")
        created = await add_assessment(session, user, course.id, _homework())
        task = await TASKS.get(session, str(created.id))
        assert task is not None and task.estimate_minutes is None
        # L'utilisateur confirme l'estimation de Lorakus (comme le fait la carte du chat).
        await set_estimate(session, user, task.id, 180, "assistant")
        [still] = await list_assessments(session)
        assert still.estimate_minutes is None  # c'est l'evenement qui previent le module
    payload = {"task_id": str(task.id), "owner_module": "academic", "owner_ref": str(created.id)}
    assert await _events() == [(TASK_ESTIMATED, payload, False)]

    assert (await OutboxRelay(database, bus).run_once()).delivered == 1

    async with database.transaction(user) as session:
        [updated] = await list_assessments(session)
        assert updated.estimate_minutes == 180
        # Rejoue : sans effet. Corriger le devoir avec la meme duree garde l'origine.
        assert await academic.on_task_estimated(session, str(created.id)) is False
        await update_assessment(session, user, created.id, _homework(estimate_minutes=180))
        again = await get_task(session, task.id)
        assert (again.estimate_minutes, again.estimate_source) == (180, "assistant")
        # Une autre duree, donnee dans la page : elle devient celle de l'utilisateur.
        await update_assessment(session, user, created.id, _homework(estimate_minutes=120))
        changed = await get_task(session, task.id)
        assert (changed.estimate_minutes, changed.estimate_source) == (120, "user")
        # Retirer la duree retire aussi son origine.
        await update_assessment(session, user, created.id, _homework())
        cleared = await get_task(session, task.id)
        assert (cleared.estimate_minutes, cleared.estimate_source) == (None, None)


async def test_the_estimate_event_is_only_a_signal(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework(estimate_minutes=60))
        ref = str(created.id)
        for payload in (
            {"owner_module": "academic", "owner_ref": "pas-un-identifiant"},
            {"owner_module": "academic", "owner_ref": str(uuid.uuid4())},
            {"owner_module": "projects", "owner_ref": ref},
            {"owner_module": "academic"},
        ):
            await publish(session, TASK_ESTIMATED, payload, user_id=user)
        # La meme duree que le devoir : rien a changer.
        await publish(
            session, TASK_ESTIMATED, {"owner_module": "academic", "owner_ref": ref}, user_id=user
        )
    assert (await OutboxRelay(database, bus).run_once()).delivered == 5
    async with database.transaction(user) as session:
        [same] = await list_assessments(session)
        assert same.estimate_minutes == 60
        assert await academic.on_task_estimated(session, "pas-un-identifiant") is False
        assert await academic.on_task_estimated(session, ref) is False
        # Une evaluation terminee ne change plus.
        await complete_assessment(session, user, created.id, NOW)
        task = await TASKS.get(session, ref)
        assert task is not None
        await session.execute(
            sa_text("UPDATE lorakus.core_tasks SET estimate_minutes = 90 WHERE id = :id"),
            {"id": task.id},
        )
        assert await academic.on_task_estimated(session, ref) is False


async def test_completing_an_assessment_keeps_the_time_spent(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework(estimate_minutes=120))
        for wrong in (0, 7 * 24 * 60 + 1):
            with pytest.raises(AcademicError, match="temps passé"):
                await complete_assessment(session, user, created.id, NOW, actual_minutes=wrong)
        await complete_assessment(session, user, created.id, NOW, actual_minutes=150)
        task = await TASKS.get(session, str(created.id))
        assert task is not None
        assert (task.status, task.actual_minutes, task.estimate_minutes) == ("done", 150, 120)


# ------------------------------------------------------------- supprimer
async def test_deleting_removes_the_task_and_a_course_takes_everything(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        ml = await add_course(session, user, "Machine Learning")
        algo = await add_course(session, user, "Algo")
        one = await add_assessment(session, user, ml.id, _homework("TP 1"))
        two = await add_assessment(session, user, ml.id, _homework("TP 2"))
        kept = await add_assessment(session, user, algo.id, _homework("TP 1"))
        personal = await add_task(session, user, NewTask("Faire les courses"))
        await complete_assessment(session, user, two.id, NOW)

        await delete_assessment(session, user, one.id)
        assert await TASKS.get(session, str(one.id)) is None
        with pytest.raises(AssessmentNotFoundError):
            await delete_assessment(session, user, one.id)

        # Le cours emporte ses evaluations (ouvertes ou terminees) et leurs taches, rien d'autre.
        assert await delete_course(session, user, ml.id) == 1
        assert await TASKS.get(session, str(two.id)) is None
        assert [c.name for c in await list_courses(session)] == ["Algo"]
        assert [a.id for a in await list_assessments(session)] == [kept.id]
        assert await list_assessments(session, "done") == []
        assert {t.id for t in await list_tasks(session)} == {
            personal.id,
            (await TASKS.get(session, str(kept.id))).id,  # type: ignore[union-attr]
        }
        with pytest.raises(CourseNotFoundError):
            await delete_course(session, user, ml.id)
    remaining = await migrator_sql("SELECT count(*) FROM lorakus.core_tasks")
    assert remaining == [(2,)]


async def test_every_change_is_audited_without_names(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Cours secret")
        created = await add_assessment(session, user, course.id, _homework("Titre secret"))
        await update_assessment(session, user, created.id, _homework("Titre secret 2"))
        await complete_assessment(session, user, created.id, NOW)
        await delete_assessment(session, user, created.id)
        await delete_course(session, user, course.id)
    rows = await migrator_sql(
        "SELECT action, details::text FROM lorakus.core_audit_events "
        "WHERE action LIKE 'academic.%' ORDER BY id"
    )
    assert [action for action, _ in rows] == [
        "academic.course_add",
        "academic.assessment_add",
        "academic.assessment_update",
        "academic.assessment_complete",
        "academic.assessment_delete",
        "academic.course_delete",
    ]
    assert all("secret" not in str(details) for _, details in rows)


# ------------------------------------------------------------- isolation
async def test_courses_and_assessments_of_another_user_are_invisible(
    database: Database, identity: IdentityService
) -> None:
    user, other = await _owner(identity), await _second()
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
        created = await add_assessment(session, user, course.id, _homework())
    async with database.transaction(other) as session:
        assert await list_courses(session) == []
        assert await list_assessments(session) == []
        assert await find_course(session, "Algo") is None
        await add_course(session, other, "Algo")  # meme nom chez un autre : permis
        with pytest.raises(CourseNotFoundError):
            await add_assessment(session, other, course.id, _homework())
        with pytest.raises(CourseNotFoundError):
            await delete_course(session, other, course.id)
        for call in (
            update_assessment(session, other, created.id, _homework("x")),
            complete_assessment(session, other, created.id, NOW),
            delete_assessment(session, other, created.id),
        ):
            with pytest.raises(AssessmentNotFoundError):
                await call
    async with database.transaction(user) as session:
        assert [a.status for a in await list_assessments(session)] == ["open"]


async def test_an_assessment_cannot_hang_under_another_users_course(
    database: Database, identity: IdentityService
) -> None:
    user, other = await _owner(identity), await _second()
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
    with pytest.raises(IntegrityError, match="fk_acad_assessments_course_id_acad_courses"):
        async with database.transaction(other) as session:
            await session.execute(
                text(
                    "INSERT INTO lorakus.acad_assessments "
                    "(id, user_id, course_id, kind, title, due_on, source_kind) "
                    "VALUES (:id, :user, :course, 'exam', 'x', '2026-11-20', 'user')"
                ),
                {"id": uuid.uuid4(), "user": other, "course": course.id},
            )


_ROW = (
    "INSERT INTO lorakus.acad_assessments (id, user_id, course_id, kind, title, due_on, "
    "weight, estimate_minutes, status, completed_at, source_kind, source_ref) VALUES "
    "(:id, :user, :course, {kind}, {title}, '2026-11-20', {weight}, {estimate}, {status}, "
    "{completed}, {source_kind}, {source_ref})"
)
_GOOD = {
    "kind": "'exam'",
    "title": "'x'",
    "weight": "NULL",
    "estimate": "NULL",
    "status": "'open'",
    "completed": "NULL",
    "source_kind": "'user'",
    "source_ref": "NULL",
}


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({}, None),
        ({"kind": "'quiz'"}, "kind"),
        ({"title": "''"}, "title"),
        ({"title": "repeat('x', 111)"}, "title"),
        ({"weight": "0"}, "weight"),
        ({"weight": "100.01"}, "weight"),
        ({"estimate": "0"}, "estimate_minutes"),
        ({"estimate": "10081"}, "estimate_minutes"),
        ({"status": "'late'"}, "status"),
        ({"status": "'done'"}, "completed_at"),
        ({"completed": "now()"}, "completed_at"),
        ({"source_kind": "'module'"}, "source"),
        ({"source_ref": "'conversation:1'"}, "source"),  # saisie dans la page : sans provenance
        ({"source_kind": "'conversation'"}, "source"),  # chat : provenance obligatoire
        ({"source_kind": "'conversation'", "source_ref": "''"}, "source"),
        ({"source_kind": "'conversation'", "source_ref": "repeat('x', 201)"}, "source"),
        ({"source_kind": "'conversation'", "source_ref": "'conversation:1'"}, None),
        ({"status": "'done'", "completed": "now()", "weight": "100", "estimate": "10080"}, None),
    ],
)
async def test_the_database_refuses_incoherent_assessments(
    database: Database,
    identity: IdentityService,
    change: dict[str, str],
    constraint: str | None,
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        course = await add_course(session, user, "Algo")
    statement = text(_ROW.format(**{**_GOOD, **change}))
    params = {"id": uuid.uuid4(), "user": user, "course": course.id}
    if constraint is None:
        async with database.transaction(user) as session:
            await session.execute(statement, params)
        return
    with pytest.raises(IntegrityError, match=f"ck_acad_assessments_{constraint}"):
        async with database.transaction(user) as session:
            await session.execute(statement, params)


_COURSE_ROW = (
    "INSERT INTO lorakus.acad_courses (id, user_id, name, name_key) "
    "VALUES (:id, :user, {name}, {key})"
)


@pytest.mark.parametrize(
    ("name", "key", "constraint"),
    [
        ("''", "'k'", "ck_acad_courses_name"),
        ("repeat('x', 81)", "'k'", "ck_acad_courses_name"),
        ("'Algo'", "''", "ck_acad_courses_name_key"),
        ("'Algo'", "'algo'", "uq_acad_courses_user_id_name_key"),
    ],
)
async def test_the_database_refuses_incoherent_courses(
    database: Database, identity: IdentityService, name: str, key: str, constraint: str
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as session:
        await add_course(session, user, "Algo")
    with pytest.raises(IntegrityError, match=constraint):
        async with database.transaction(user) as session:
            statement = text(_COURSE_ROW.format(name=name, key=key))
            await session.execute(statement, {"id": uuid.uuid4(), "user": user})
