"""Vue « Aujourd'hui » (PR 47 et 49) par l'API : cadre du jour, agenda, plan propose, retards,
echeances, et le scenario 2 de bout en bout. Le planificateur lui-meme est teste dans
tests/unit/test_planner.py ; ici, ce qui l'entoure : fuseau du compte, RLS, lecture seule,
nuit qui passe minuit.

Repere : mercredi 18 novembre 2026, 07:30 a Ankara (04:30 UTC).
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import test_chat_tools
from conftest import BASE_URL, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD, of, send, use_model
from test_task_tools import confirm, fix_clock, owner_id, seed, set_timezone

from lorakus.ai.testing import FakeReply
from lorakus.api.routes import planning as planning_route
from lorakus.core.identity.passwords import HASHER
from lorakus.core.planning.days import BreakKind, build_frame, set_frame
from lorakus.core.planning.service import (
    AgendaItem,
    ModuleAgenda,
    ModuleTasks,
    NewTask,
    add_task,
    complete_task,
)

pytestmark = pytest.mark.integration

owner = test_chat_tools.owner
conversation = test_chat_tools.conversation

TODAY = "/api/v1/planning/today"
ANKARA = ZoneInfo("Europe/Istanbul")
DAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 4, 30, tzinfo=UTC)  # 07:30 a Ankara
SNAPSHOT = (
    "SELECT (SELECT count(*) FROM lorakus.core_agenda_entries), "
    "(SELECT count(*) FROM lorakus.core_tasks), (SELECT count(*) FROM lorakus.core_outbox), "
    "(SELECT count(*) FROM lorakus.core_audit_events), "
    "(SELECT count(*) FROM lorakus.core_planning_days), "
    "(SELECT coalesce(max(updated_at), 'epoch') FROM lorakus.core_tasks)"
)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ANKARA).astimezone(UTC)


def fix_now(client: TestClient, now: datetime = NOW) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[planning_route.get_now] = lambda: now


def today(client: TestClient) -> dict[str, Any]:
    response = client.get(TODAY)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def local(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(ANKARA).strftime("%H:%M")


def ankara(client: TestClient) -> None:
    set_timezone(client, "Europe/Istanbul")
    fix_now(client)


async def work(
    session: Any,
    user: uuid.UUID,
    start: str = "08:00",
    end: str = "22:00",
    *breaks: tuple[BreakKind, str, str],
    day: date = DAY,
    tz: ZoneInfo = ANKARA,
) -> None:
    """Le cadre du jour, comme si l'utilisateur l'avait confirme."""
    frame = build_frame(
        day,
        tz,
        time.fromisoformat(start),
        time.fromisoformat(end),
        [(kind, time.fromisoformat(a), time.fromisoformat(b)) for kind, a, b in breaks],
    )
    await set_frame(session, user, frame)


async def _agenda(session: Any, user: uuid.UUID) -> None:
    await ModuleAgenda("calendars").replace_source(
        session,
        user,
        "cours",
        [
            AgendaItem("c1", "Machine Learning", at(9), at(12), location="B-104"),
            AgendaItem("c2", "Réseaux", at(13, 30), at(15)),
            AgendaItem(
                "hier",
                "Cours d'hier",
                at(9, day=DAY - timedelta(days=1)),
                at(10, day=DAY - timedelta(days=1)),
            ),
            AgendaItem(
                "demain",
                "Cours de demain",
                at(9, day=DAY + timedelta(days=1)),
                at(10, day=DAY + timedelta(days=1)),
            ),
            AgendaItem("ferie", "Jour férié", start_date=DAY, end_date=DAY + timedelta(days=1)),
        ],
    )


def test_a_session_is_required(api: TestClient) -> None:
    assert api.get(TODAY).status_code == 401


def test_an_empty_day(owner: TestClient) -> None:
    ankara(owner)
    body = today(owner)
    assert (body["day"], body["timezone"]) == ("2026-11-18", "Europe/Istanbul")
    assert datetime.fromisoformat(body["generated_at"]) == NOW
    assert body["frame"] is None  # rien de dit : aucune heure supposee
    assert (body["agenda"], body["plan"], body["unplanned"], body["unestimated"]) == (
        [],
        [],
        [],
        [],
    )
    assert (body["overdue"], body["upcoming"], body["planned_minutes"]) == ([], [], 0)


def test_the_day_shows_agenda_plan_overdue_and_upcoming(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> dict[str, uuid.UUID]:
        await _agenda(session, user)
        await work(session, user)
        ids = {
            "late": (
                await add_task(session, user, NewTask("Rapport", DAY - timedelta(days=2), 60, 3))
            ).id,
            "errand": (await add_task(session, user, NewTask("Courses"))).id,
            "far": (
                await add_task(session, user, NewTask("Dossier", DAY + timedelta(days=8), 45))
            ).id,
            "week": (
                await add_task(session, user, NewTask("Exposé", DAY + timedelta(days=7), 45))
            ).id,
            "tonight": (await add_task(session, user, NewTask("Quiz", DAY, 30, 1))).id,
        }
        homework = await ModuleTasks("academic").upsert(
            session,
            user,
            "ref-1",
            "ML : TP 2",
            due_on=DAY + timedelta(days=2),
            estimate_minutes=180,
        )
        ids["homework"] = homework.id
        done = await add_task(session, user, NewTask("Déjà fait", DAY, 30))
        await complete_task(session, user, done.id, NOW)
        return ids

    ids = {name: str(value) for name, value in seed(_seed).items()}

    body = today(owner)

    # Agenda du jour seulement : la journee entiere d'abord, puis par heure.
    assert [(e["title"], e["all_day"], e["location"], e["module"]) for e in body["agenda"]] == [
        ("Jour férié", True, None, "calendars"),
        ("Machine Learning", False, "B-104", "calendars"),
        ("Réseaux", False, None, "calendars"),
    ]
    assert body["agenda"][0]["starts_at"] is None
    assert (local(body["agenda"][1]["starts_at"]), local(body["agenda"][1]["ends_at"])) == (
        "09:00",
        "12:00",
    )
    # Plan : retard, puis aujourd'hui, puis vendredi, J+7, J+8.
    assert [
        (b["task"]["id"], local(b["starts_at"]), local(b["ends_at"]), b["minutes"])
        for b in body["plan"]
    ] == [
        (ids["late"], "08:00", "09:00", 60),
        (ids["tonight"], "12:00", "12:30", 30),
        (ids["homework"], "12:45", "13:30", 45),
        (ids["homework"], "15:00", "17:00", 120),
        (ids["homework"], "17:15", "17:30", 15),
        (ids["week"], "17:45", "18:30", 45),
        (ids["far"], "18:45", "19:30", 45),
    ]
    assert body["planned_minutes"] == 60 + 30 + 180 + 45 + 45 == 360
    assert body["unplanned"] == []
    # La tache sans duree n'est pas placee : elle est « a estimer ».
    [waiting] = body["unestimated"]
    assert (waiting["id"], waiting["title"], waiting["estimate_minutes"]) == (
        ids["errand"],
        "Courses",
        None,
    )
    assert body["frame"] == {
        "off": False,
        "starts_at": at(8).isoformat().replace("+00:00", "Z"),
        "ends_at": at(22).isoformat().replace("+00:00", "Z"),
        "breaks": [],
    }
    first = body["plan"][0]["task"]
    assert first == {
        "id": ids["late"],
        "title": "Rapport",
        "due_on": "2026-11-16",
        "days_left": -2,
        "overdue": True,
        "estimate_minutes": 60,
        "priority": 3,
        "module": None,
    }
    assert body["plan"][2]["task"]["module"] == "academic"
    assert [t["id"] for t in body["overdue"]] == [ids["late"]]
    # Echeances : d'aujourd'hui a J+7 inclus ; ni le retard, ni J+8, ni la tache sans date.
    assert [(t["id"], t["days_left"], t["overdue"]) for t in body["upcoming"]] == [
        (ids["tonight"], 0, False),
        (ids["homework"], 2, False),
        (ids["week"], 7, False),
    ]


def test_a_task_without_duration_is_listed_to_estimate_never_placed(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await work(session, user)
        await add_task(session, user, NewTask("Courses"))
        await add_task(session, user, NewTask("Lecture", DAY, 45))

    seed(_seed)
    body = today(owner)
    assert [(b["task"]["title"], b["minutes"]) for b in body["plan"]] == [("Lecture", 45)]
    assert [t["title"] for t in body["unestimated"]] == ["Courses"]


def test_without_a_frame_the_day_proposes_nothing_but_keeps_deadlines(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await _agenda(session, user)
        await add_task(session, user, NewTask("Lecture", DAY, 45))

    seed(_seed)
    body = today(owner)
    assert (body["frame"], body["plan"], body["planned_minutes"]) == (None, [], 0)
    assert [(u["task"]["title"], u["minutes"]) for u in body["unplanned"]] == [("Lecture", 45)]
    assert [t["title"] for t in body["upcoming"]] == ["Lecture"]
    assert len(body["agenda"]) == 3  # l'agenda reste visible


def test_a_day_off_proposes_nothing(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        from lorakus.core.planning.days import day_off

        await set_frame(session, user, day_off(DAY))
        await add_task(session, user, NewTask("Lecture", DAY, 45))

    seed(_seed)
    body = today(owner)
    assert body["frame"] == {"off": True, "starts_at": None, "ends_at": None, "breaks": []}
    assert body["plan"] == []
    assert [u["minutes"] for u in body["unplanned"]] == [45]


def test_breaks_show_in_the_frame_and_are_kept_free(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await work(
            session, user, "10:00", "20:00", ("meal", "12:30", "13:15"), ("sport", "18:00", "19:00")
        )
        await add_task(session, user, NewTask("Rapport", DAY, 300))

    seed(_seed)
    body = today(owner)
    assert [
        (b["kind"], b["label"], local(b["starts_at"]), local(b["ends_at"]))
        for b in body["frame"]["breaks"]
    ] == [("meal", "Repas", "12:30", "13:15"), ("sport", "Sport", "18:00", "19:00")]
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]] == [
        ("10:00", "12:00"),
        ("13:15", "15:15"),
        ("15:30", "16:30"),
    ]


def test_a_night_of_work_is_still_the_same_day_after_midnight(owner: TestClient) -> None:
    """Nuit blanche : a 2 h du matin, la journee en cours est encore celle de la veille."""
    set_timezone(owner, "Europe/Istanbul")
    tomorrow = DAY + timedelta(days=1)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await work(session, user, "21:00", "05:00", ("meal", "23:30", "00:15"))
        await add_task(session, user, NewTask("Projet", tomorrow, 300))
        await ModuleAgenda("calendars").replace_source(
            session,
            user,
            "cours",
            [
                AgendaItem("tard", "Garde", at(3, day=tomorrow), at(3, 30, day=tomorrow)),
                AgendaItem("matin", "Cours du matin", at(9, day=tomorrow), at(10, day=tomorrow)),
            ],
        )

    seed(_seed)
    fix_now(owner, at(2, 0, tomorrow))
    body = today(owner)
    assert body["day"] == "2026-11-18"  # toujours la journee commencee la veille
    assert [e["title"] for e in body["agenda"]] == ["Garde"]  # dans la nuit, pas le cours de 9 h
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]] == [
        ("02:00", "03:00"),
        ("03:30", "05:00"),
    ]
    assert [u["minutes"] for u in body["unplanned"]] == [300 - 60 - 90]
    # La nuit finie, on passe au jour suivant : sans cadre, rien n'est propose.
    fix_now(owner, at(5, 0, tomorrow))
    body = today(owner)
    assert (body["day"], body["frame"], body["plan"]) == ("2026-11-19", None, [])


def test_what_does_not_fit_is_listed_with_the_time_left(owner: TestClient) -> None:
    set_timezone(owner, "Europe/Istanbul")
    fix_now(owner, at(20, 50))  # il reste 1 h 10 avant 22 h

    async def _seed(session: Any, user: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        await work(session, user)
        big = await add_task(session, user, NewTask("Gros devoir", DAY, 180))
        small = await add_task(session, user, NewTask("Lecture", DAY + timedelta(days=1), 40))
        return big.id, small.id

    big, small = seed(_seed)
    body = today(owner)
    assert [
        (b["task"]["id"], local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]
    ] == [(str(big), "21:00", "22:00")]
    assert [(u["task"]["id"], u["minutes"]) for u in body["unplanned"]] == [
        (str(big), 120),
        (str(small), 40),
    ]

    fix_now(owner, at(22, 30))  # plage de travail finie : plus de plan, tout reste
    body = today(owner)
    assert body["frame"] is not None
    assert (body["plan"], body["planned_minutes"]) == ([], 0)
    assert [(u["task"]["id"], u["minutes"]) for u in body["unplanned"]] == [
        (str(big), 180),
        (str(small), 40),
    ]
    assert body["day"] == "2026-11-18"


def test_today_is_the_day_of_the_account_timezone(owner: TestClient) -> None:
    """A 23:30 UTC le 18, il est deja le 19 a Ankara et encore le 18 a New York."""
    fix_now(owner, datetime(2026, 11, 18, 23, 30, tzinfo=UTC))

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await add_task(session, user, NewTask("Pour le 18", date(2026, 11, 18), 30))

    seed(_seed)
    set_timezone(owner, "Europe/Istanbul")
    east = today(owner)
    assert (east["day"], east["timezone"]) == ("2026-11-19", "Europe/Istanbul")
    assert [(t["days_left"], t["overdue"]) for t in east["overdue"]] == [(-1, True)]
    assert east["upcoming"] == []
    set_timezone(owner, "America/New_York")

    async def _frame(session: Any, user: uuid.UUID) -> None:
        # Le cadre de mercredi, dit a New York.
        await work(session, user, day=date(2026, 11, 18), tz=ZoneInfo("America/New_York"))

    seed(_frame)
    west = today(owner)
    assert (west["day"], west["overdue"]) == ("2026-11-18", [])
    assert [(t["days_left"], t["overdue"]) for t in west["upcoming"]] == [(0, False)]
    # 18:30 a New York : le plan commence maintenant, dans SON fuseau.
    [block] = west["plan"]
    assert datetime.fromisoformat(block["starts_at"]) == datetime(2026, 11, 18, 23, 30, tzinfo=UTC)


def test_reading_the_day_writes_nothing(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await _agenda(session, user)
        await work(session, user)
        await add_task(session, user, NewTask("Rapport", DAY, 120))

    seed(_seed)
    before = asyncio.run(migrator_sql(SNAPSHOT))
    entries = asyncio.run(
        migrator_sql(
            "SELECT id, title, starts_at, ends_at FROM lorakus.core_agenda_entries ORDER BY id"
        )
    )
    for _ in range(3):
        assert len(today(owner)["plan"]) == 2  # deux blocs d'une heure autour des cours
    # Le plan est une proposition : ni creneau, ni tache, ni evenement, ni trace d'audit.
    assert asyncio.run(migrator_sql(SNAPSHOT)) == before
    assert (
        asyncio.run(
            migrator_sql(
                "SELECT id, title, starts_at, ends_at FROM lorakus.core_agenda_entries ORDER BY id"
            )
        )
        == entries
    )


def test_the_route_cannot_write_even_if_the_code_tried(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La transaction est en lecture seule : PostgreSQL refuse l'ecriture."""
    fix_now(owner)
    user = owner_id()

    async def _writes(session: Any, now: datetime) -> Any:
        await ModuleAgenda("calendars").replace_source(
            session, user, "plan", [AgendaItem("k", "Bloc", at(9), at(10))]
        )

    monkeypatch.setattr(planning_route, "read_today", _writes)
    with pytest.raises(DBAPIError, match="read-only transaction"):
        owner.get(TODAY)
    assert asyncio.run(migrator_sql("SELECT count(*) FROM lorakus.core_agenda_entries")) == [(0,)]


def test_another_user_sees_only_their_own_day(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await _agenda(session, user)
        await work(session, user)
        await add_task(session, user, NewTask("Rapport", DAY, 60))

    seed(_seed)
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'user')",
            {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
        )
    )
    other = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    assert (
        other.post(
            "/api/v1/auth/login", json={"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
        ).status_code
        == 204
    )
    theirs = today(other)
    assert (theirs["agenda"], theirs["plan"], theirs["upcoming"]) == ([], [], [])
    assert theirs["frame"] is None  # le cadre du proprietaire n'est pas le sien
    assert theirs["timezone"] == "Europe/Paris"  # son propre reglage, pas celui du proprietaire
    assert len(today(owner)["plan"]) == 1


# --------------------------------------------------- scenario 2 (ROADMAP)
def test_scenario_2_the_homework_added_in_the_chat_shows_in_courses_and_today(
    owner: TestClient, conversation: str
) -> None:
    """« Ajoute le devoir de Machine Learning pour vendredi, environ 3 h » → confirmation →
    tache visible dans /academic et dans Aujourd'hui."""
    assert owner.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    ankara(owner)
    fix_clock(owner, NOW)
    seed(_agenda)
    seed(work)
    arguments = {"course": "Machine Learning", "due_on": "2026-11-20", "estimate_minutes": 180}
    use_model(
        owner,
        FakeReply("", tool_calls=(("academic__add_assessment", arguments),)),
        "Confirme-la ci-dessous.",
    )
    message = "Ajoute le devoir de Machine Learning pour vendredi, environ 3 h"
    [card] = of(send(owner, conversation, message), "card")
    assert "Échéance : vendredi 20 novembre 2026 (dans 2 jours)" in card["summary"]

    # Avant le clic : rien nulle part.
    assert owner.get("/api/v1/academic/assessments").json() == []
    assert (today(owner)["plan"], today(owner)["upcoming"]) == ([], [])

    assert confirm(owner, card) == 200

    [assessment] = owner.get("/api/v1/academic/assessments").json()
    assert (assessment["course_name"], assessment["due_on"], assessment["estimate_minutes"]) == (
        "Machine Learning",
        "2026-11-20",
        180,
    )
    body = today(owner)
    [due] = body["upcoming"]
    assert (due["title"], due["due_on"], due["days_left"], due["module"]) == (
        "Machine Learning : Devoir",
        "2026-11-20",
        2,
        "academic",
    )
    # Trois heures proposees autour des cours du jour, jamais pendant.
    assert [
        (b["task"]["id"], local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]
    ] == [
        (due["id"], "08:00", "09:00"),
        (due["id"], "12:00", "13:30"),
        (due["id"], "15:00", "15:30"),
    ]
    assert body["planned_minutes"] == 180
    # Rien n'a ete ecrit dans l'agenda : il ne contient que les creneaux de sa source.
    rows = asyncio.run(
        migrator_sql("SELECT count(*), count(DISTINCT source_key) FROM lorakus.core_agenda_entries")
    )
    assert rows == [(5, 1)]
