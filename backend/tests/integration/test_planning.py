"""Planning du Core (PR 44, ADR 0018) : taches, ports des modules, agenda, fuseau du compte.

Tout s'execute en lorakus_app, sous la RLS : un test qui passerait en proprietaire des
tables ne prouverait rien.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import migrator_sql
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from lorakus.core.account.service import set_timezone, timezone_name, user_timezone
from lorakus.core.identity.service import IdentityService
from lorakus.core.planning import service as planning
from lorakus.core.planning.service import (
    AgendaItem,
    InvalidAgendaEntryError,
    InvalidTaskError,
    ModuleAgenda,
    ModuleTasks,
    NewTask,
    TaskLimitError,
    TaskNotFoundError,
    TaskStateError,
    add_task,
    agenda_for_days,
    complete_task,
    delete_task,
    get_task,
    list_tasks,
)
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
PARIS = ZoneInfo("Europe/Paris")
ISTANBUL = ZoneInfo("Europe/Istanbul")


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


# ------------------------------------------------------------------ taches
async def test_open_tasks_come_by_due_date_then_priority(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as s:
        await add_task(s, user, NewTask("Sans échéance", priority=1))
        await add_task(s, user, NewTask("Vendredi", due_on=date(2026, 11, 20)))
        await add_task(s, user, NewTask("Vendredi urgent", due_on=date(2026, 11, 20), priority=1))
        await add_task(s, user, NewTask("Hier", due_on=date(2026, 11, 17)))
    async with database.transaction(user) as s:
        tasks = await list_tasks(s)
    assert [t.title for t in tasks] == ["Hier", "Vendredi urgent", "Vendredi", "Sans échéance"]
    today = date(2026, 11, 18)
    assert [t.overdue(today) for t in tasks] == [True, False, False, False]
    # Le jour meme n'est pas un retard.
    assert not tasks[1].overdue(date(2026, 11, 20))


async def test_titles_are_cleaned_and_bad_values_refused(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as s:
        task = await add_task(s, user, NewTask("  Rendre\nle​ TP‮  "))
        assert task.title == "Rendre le TP"
        for bad in (
            NewTask("   "),
            NewTask("x" * 201),
            NewTask("ok", priority=0),
            NewTask("ok", estimate_minutes=0),
            NewTask("ok", estimate_minutes=7 * 24 * 60 + 1),
            NewTask("ok", notes="a\x00b"),
        ):
            with pytest.raises(InvalidTaskError):
                await add_task(s, user, bad)


async def test_subtasks_stay_one_level_deep_and_follow_their_parent(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as s:
        parent = await add_task(s, user, NewTask("Projet"))
        child = await add_task(s, user, NewTask("Étape 1", parent_id=parent.id))
        await add_task(s, user, NewTask("Étape 2", parent_id=parent.id))
        with pytest.raises(TaskStateError):
            await add_task(s, user, NewTask("Trop profond", parent_id=child.id))
        with pytest.raises(TaskNotFoundError):
            await add_task(s, user, NewTask("Orpheline", parent_id=uuid.uuid4()))
        assert (await get_task(s, parent.id)).open_subtasks == 2
        # Terminer le parent termine ses sous-taches encore ouvertes.
        assert await complete_task(s, user, parent.id, NOW) == 3
        with pytest.raises(TaskStateError):
            await add_task(s, user, NewTask("Après coup", parent_id=parent.id))
        with pytest.raises(TaskStateError):
            await complete_task(s, user, parent.id, NOW)
        done = await list_tasks(s, "done")
        assert {t.title for t in done} == {"Projet", "Étape 1", "Étape 2"}
        assert all(t.completed_at == NOW for t in done)
        # Supprimer le parent supprime ses sous-taches.
        await delete_task(s, user, parent.id)
        assert await list_tasks(s, "done") == []


async def test_limits_on_open_tasks_and_subtasks(
    database: Database, identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _owner(identity)
    monkeypatch.setattr(planning, "MAX_OPEN_TASKS", 3)
    monkeypatch.setattr(planning, "MAX_SUBTASKS", 1)
    async with database.transaction(user) as s:
        parent = await add_task(s, user, NewTask("Parent"))
        await add_task(s, user, NewTask("Enfant", parent_id=parent.id))
        with pytest.raises(TaskLimitError):
            await add_task(s, user, NewTask("Second enfant", parent_id=parent.id))
        await add_task(s, user, NewTask("Troisième"))
        with pytest.raises(TaskLimitError):
            await add_task(s, user, NewTask("Quatrième"))


async def test_every_change_is_audited_without_the_title(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as s:
        task = await add_task(s, user, NewTask("Titre secret"))
        await complete_task(s, user, task.id, NOW)
        await delete_task(s, user, task.id)
    rows = await migrator_sql(
        "SELECT action, details::text FROM lorakus.core_audit_events "
        "WHERE action LIKE 'planning.%' ORDER BY id"
    )
    assert [r[0] for r in rows] == [
        "planning.task_add",
        "planning.task_complete",
        "planning.task_delete",
    ]
    assert all("Titre secret" not in str(r[1]) and str(task.id) in str(r[1]) for r in rows)


# ------------------------------------------------------- port des modules
async def test_a_module_only_touches_its_own_tasks(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    academic, projects = ModuleTasks("academic"), ModuleTasks("projects")
    async with database.transaction(user) as s:
        first = await academic.upsert(
            s, user, "devoir-1", "Devoir de ML", due_on=date(2026, 11, 20)
        )
        again = await academic.upsert(
            s, user, "devoir-1", "Devoir de ML (v2)", estimate_minutes=180
        )
        assert again.id == first.id and again.title == "Devoir de ML (v2)"
        assert again.due_on is None and again.estimate_minutes == 180
        mine = await add_task(s, user, NewTask("Personnelle"))

        # Un autre module ne voit, ne termine ni ne supprime la tache d'academic.
        assert await projects.get(s, "devoir-1") is None
        assert not await projects.complete(s, "devoir-1", NOW)
        assert not await projects.delete(s, "devoir-1")
        # Une tache personnelle n'appartient a aucun module.
        assert not await academic.complete(s, str(mine.id), NOW)

        # L'utilisateur termine la tache du module, mais ne la supprime pas depuis le chat.
        with pytest.raises(TaskStateError):
            await delete_task(s, user, first.id)
        assert await academic.complete(s, "devoir-1", NOW)
        assert not await academic.complete(s, "devoir-1", NOW)
        # Une mise a jour du contenu ne rouvre pas une tache terminee.
        updated = await academic.upsert(s, user, "devoir-1", "Devoir de ML (v3)")
        assert updated.status == "done"
        assert await academic.delete(s, "devoir-1")
        assert await academic.get(s, "devoir-1") is None


def test_module_ports_refuse_invalid_identifiers() -> None:
    for bad in ("", "Academic", "a", "academic.tasks", "x" * 40):
        with pytest.raises(ValueError):
            ModuleTasks(bad)
        with pytest.raises(ValueError):
            ModuleAgenda(bad)


# --------------------------------------------------------------- isolation
async def test_tasks_and_agenda_of_another_user_are_invisible(
    database: Database, identity: IdentityService
) -> None:
    user, other = await _owner(identity), await _second()
    async with database.transaction(other) as s:
        theirs = await add_task(s, other, NewTask("La sienne"))
        await ModuleAgenda("calendars").replace_source(
            s,
            other,
            "abonnement",
            [AgendaItem("x", "Son cours", NOW, NOW + timedelta(hours=1))],
        )
    async with database.transaction(user) as s:
        assert await list_tasks(s) == []
        assert await agenda_for_days(s, date(2026, 11, 18), 1, PARIS) == []
        with pytest.raises(TaskNotFoundError):
            await complete_task(s, user, theirs.id, NOW)
        with pytest.raises(TaskNotFoundError):
            await delete_task(s, user, theirs.id)


async def test_a_subtask_cannot_hang_under_another_users_task(
    database: Database, identity: IdentityService
) -> None:
    user, other = await _owner(identity), await _second()
    async with database.transaction(other) as s:
        theirs = await add_task(s, other, NewTask("La sienne"))
    # Meme en contournant le service, la cle composee refuse le rattachement.
    with pytest.raises(IntegrityError):
        async with database.transaction(user) as s:
            await s.execute(
                text(
                    "INSERT INTO lorakus.core_tasks (id, user_id, parent_id, title, source_kind) "
                    "VALUES (:id, :user, :parent, 'Pirate', 'user')"
                ),
                {"id": uuid.uuid4(), "user": user, "parent": theirs.id},
            )


async def test_the_database_refuses_incoherent_tasks(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    for status, completed_at, module, ref in (
        ("done", None, None, None),  # terminee sans date
        ("open", NOW, None, None),  # ouverte avec une date de fin
        ("open", None, "academic", None),  # module sans reference
        ("open", None, None, "devoir-1"),  # reference sans module
        ("open", None, "Academic!", "x"),  # identifiant de module invalide
    ):
        with pytest.raises(IntegrityError):
            async with database.transaction(user) as s:
                await s.execute(
                    text(
                        "INSERT INTO lorakus.core_tasks (id, user_id, title, source_kind, "
                        "status, completed_at, owner_module, owner_ref) VALUES (:id, :user, "
                        "'t', 'user', :status, :completed_at, :module, :ref)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "user": user,
                        "status": status,
                        "completed_at": completed_at,
                        "module": module,
                        "ref": ref,
                    },
                )


async def test_the_database_refuses_incoherent_agenda_entries(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    day = date(2026, 11, 18)
    later = NOW + timedelta(hours=1)
    for starts_at, ends_at, start_date, end_date, module, source, key in (
        (NOW, NOW, None, None, None, None, None),  # duree nulle
        (NOW, None, None, None, None, None, None),  # sans fin
        (None, None, day, day, None, None, None),  # journee vide
        (NOW, later, day, day + timedelta(days=1), None, None, None),  # les deux
        (None, None, None, None, None, None, None),  # aucun
        (NOW, later, None, None, "calendars", None, "k"),  # module sans source
        (NOW, later, None, None, None, "src", "k"),  # source sans module
        (NOW, later, None, None, "calendars", "src", None),  # occurrence absente
    ):
        with pytest.raises(IntegrityError):
            async with database.transaction(user) as s:
                await s.execute(
                    text(
                        "INSERT INTO lorakus.core_agenda_entries (id, user_id, title, starts_at, "
                        "ends_at, start_date, end_date, owner_module, source_key, external_key) "
                        "VALUES (:id, :user, 't', :starts_at, :ends_at, :start_date, :end_date, "
                        ":module, :source, :key)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "user": user,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "start_date": start_date,
                        "end_date": end_date,
                        "module": module,
                        "source": source,
                        "key": key,
                    },
                )


# ------------------------------------------------------------------ agenda
def _at(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


async def test_replacing_a_source_is_idempotent_and_leaves_other_sources(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    day = date(2026, 11, 18)
    calendars, academic = ModuleAgenda("calendars"), ModuleAgenda("academic")
    week = [
        AgendaItem("cours-1", "CENG 4xx", _at(day, 12, 40, ISTANBUL), _at(day, 13, 30, ISTANBUL)),
        AgendaItem("cours-2", "CSEC 5xx", _at(day, 13, 40, ISTANBUL), _at(day, 14, 30, ISTANBUL)),
    ]
    async with database.transaction(user) as s:
        assert await calendars.replace_source(s, user, "metu", week) == 2
        assert await calendars.replace_source(s, user, "metu", week) == 2  # rejoue : pas de doublon
        await academic.replace_source(
            s,
            user,
            "examens",
            [AgendaItem("exam", "Examen", start_date=day, end_date=day + timedelta(days=1))],
        )
        assert len(await agenda_for_days(s, day, 1, ISTANBUL)) == 3
        # Le nouvel envoi remplace l'ancien pour cette source seulement.
        await calendars.replace_source(s, user, "metu", week[:1])
        titles = [e.title for e in await agenda_for_days(s, day, 1, ISTANBUL)]
        assert titles == ["Examen", "CENG 4xx"]  # journee entiere d'abord
        assert await calendars.clear_source(s, "metu") == 1
        assert [e.title for e in await agenda_for_days(s, day, 1, ISTANBUL)] == ["Examen"]


async def test_two_modules_with_the_same_source_name_stay_apart(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    day = date(2026, 11, 18)
    item = AgendaItem("k", "Créneau", _at(day, 10, 0, PARIS), _at(day, 11, 0, PARIS))
    async with database.transaction(user) as s:
        await ModuleAgenda("calendars").replace_source(s, user, "principal", [item])
        await ModuleAgenda("academic").replace_source(s, user, "principal", [item])
        await ModuleAgenda("academic").replace_source(s, user, "principal", [])
        assert await ModuleAgenda("academic").clear_source(s, "principal") == 0
        views = await agenda_for_days(s, day, 1, PARIS)
        assert [(v.title, v.owner_module) for v in views] == [("Créneau", "calendars")]


async def test_bad_agenda_items_are_refused_before_anything_is_written(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    day = date(2026, 11, 18)
    good = AgendaItem("ok", "Cours", _at(day, 10, 0, PARIS), _at(day, 11, 0, PARIS))
    naive = datetime(2026, 11, 18, 10, 0)
    bad_items = [
        AgendaItem("a", "Fin avant début", _at(day, 11, 0, PARIS), _at(day, 10, 0, PARIS)),
        AgendaItem("b", "Sans fuseau", naive, naive + timedelta(hours=1)),
        AgendaItem("c", "Les deux", _at(day, 10, 0, PARIS), _at(day, 11, 0, PARIS), day, day),
        AgendaItem("d", "Aucun"),
        AgendaItem("e", "Journée vide", start_date=day, end_date=day),
        AgendaItem("f", "   ", _at(day, 10, 0, PARIS), _at(day, 11, 0, PARIS)),
    ]
    agenda = ModuleAgenda("calendars")
    async with database.transaction(user) as s:
        await agenda.replace_source(s, user, "src", [good])
        for bad in bad_items:
            with pytest.raises(InvalidAgendaEntryError):
                await agenda.replace_source(s, user, "src", [good, bad])
        with pytest.raises(InvalidAgendaEntryError):
            await agenda.replace_source(s, user, "src", [good, good])  # occurrence en double
        # Rien n'a ete efface par les envois refuses.
        assert [e.title for e in await agenda_for_days(s, day, 1, PARIS)] == ["Cours"]


async def test_a_day_view_follows_the_users_timezone(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    late = AgendaItem(
        "soir",
        "Séance tardive",
        datetime(2026, 11, 18, 22, 30, tzinfo=UTC),  # 23:30 a Paris, 01:30 le 19 a Ankara
        datetime(2026, 11, 18, 23, 30, tzinfo=UTC),
    )
    across = AgendaItem(
        "nuit",
        "De 23 h à 1 h",
        _at(date(2026, 11, 20), 23, 0, PARIS),
        _at(date(2026, 11, 21), 1, 0, PARIS),
    )
    async with database.transaction(user) as s:
        await ModuleAgenda("calendars").replace_source(s, user, "src", [late, across])
        on_18_paris = [e.title for e in await agenda_for_days(s, date(2026, 11, 18), 1, PARIS)]
        on_18_ankara = [e.title for e in await agenda_for_days(s, date(2026, 11, 18), 1, ISTANBUL)]
        on_19_ankara = [e.title for e in await agenda_for_days(s, date(2026, 11, 19), 1, ISTANBUL)]
        assert on_18_paris == ["Séance tardive"]
        assert on_18_ankara == []
        assert on_19_ankara == ["Séance tardive"]
        # Un creneau qui passe minuit compte pour les deux jours.
        assert [e.title for e in await agenda_for_days(s, date(2026, 11, 20), 1, PARIS)] == [
            "De 23 h à 1 h"
        ]
        assert [e.title for e in await agenda_for_days(s, date(2026, 11, 21), 1, PARIS)] == [
            "De 23 h à 1 h"
        ]


async def test_the_day_of_the_clock_change_keeps_its_last_hour(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    # Le 25 octobre 2026 dure 25 h a Paris : un creneau a 23 h 30 en fait encore partie.
    item = AgendaItem(
        "x", "Tard", _at(date(2026, 10, 25), 23, 30, PARIS), _at(date(2026, 10, 25), 23, 50, PARIS)
    )
    async with database.transaction(user) as s:
        await ModuleAgenda("calendars").replace_source(s, user, "src", [item])
        assert len(await agenda_for_days(s, date(2026, 10, 25), 1, PARIS)) == 1
        assert await agenda_for_days(s, date(2026, 10, 26), 1, PARIS) == []


# ---------------------------------------------------------- fuseau du compte
async def test_timezone_defaults_to_paris_and_is_audited_without_the_place(
    database: Database, identity: IdentityService
) -> None:
    user = await _owner(identity)
    async with database.transaction(user) as s:
        assert await timezone_name(s) == "Europe/Paris"
        await set_timezone(s, user, "Europe/Istanbul")
        await set_timezone(s, user, "Europe/Istanbul")  # deux fois : une seule ligne
    async with database.transaction(user) as s:
        assert str(await user_timezone(s)) == "Europe/Istanbul"
    rows = await migrator_sql(
        "SELECT details::text FROM lorakus.core_audit_events "
        "WHERE action = 'account.timezone_update'"
    )
    assert len(rows) == 2 and all("Istanbul" not in str(r[0]) for r in rows)
    other = await _second()
    async with database.transaction(other) as s:
        assert await timezone_name(s) == "Europe/Paris"  # le reglage du premier ne fuit pas
