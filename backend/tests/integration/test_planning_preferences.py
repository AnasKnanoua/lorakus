"""Preferences de planification (PR 48) : service sous RLS, cartes du chat, routes, et le
scenario 6 de bout en bout (preference dite en conversation → carte → confirmee → utilisee
par le planificateur).

Repere : mercredi 18 novembre 2026, 07:30 a Ankara.
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, time
from typing import Any, cast

import pytest
import test_chat_tools
from conftest import BASE_URL, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD, of, requests, send, use_model
from test_task_tools import confirm, fix_clock, seed
from test_today import ankara, local, today

from lorakus.ai.testing import FakeReply
from lorakus.core.identity.passwords import HASHER
from lorakus.core.identity.service import IdentityService
from lorakus.core.planning.preferences import (
    DEFAULTS,
    InvalidPreferenceError,
    PlanningPrefs,
    TimeRange,
    clear_preference,
    load,
    preview,
    set_preference,
    stored,
)
from lorakus.core.planning.service import NewTask, add_task
from lorakus.db.database import Database
from lorakus_modules.assistant.service import PENDING_FOR_MODEL

pytestmark = pytest.mark.integration

owner = test_chat_tools.owner
conversation = test_chat_tools.conversation

PREFERENCES = "/api/v1/planning/preferences"
SET = "assistant__set_preference"
CLEAR = "assistant__clear_preference"
LIST = "assistant__list_preferences"
PASSWORD = "mot de passe de test assez long"
NOW = datetime(2026, 11, 18, 4, 30, tzinfo=UTC)
LUNCH = {"start": "12:30", "end": "13:30"}
ROWS = (
    "SELECT key, value, source_kind, source_ref FROM lorakus.core_planning_preferences ORDER BY key"
)


def rows() -> list[tuple[Any, ...]]:
    return asyncio.run(migrator_sql(ROWS))


def listed(client: TestClient) -> dict[str, tuple[str, bool]]:
    response = client.get(PREFERENCES)
    assert response.status_code == 200, response.text
    return {p["key"]: (p["value"], p["is_default"]) for p in response.json()}


# ---------------------------------------------------------------- service
@pytest.mark.anyio
async def test_preferences_are_set_replaced_and_cleared(
    database: Database, identity: IdentityService
) -> None:
    user = await identity.create_owner("a@example.com", PASSWORD)
    async with database.transaction(user) as session:
        assert await load(session) == DEFAULTS and await stored(session) == []
        await set_preference(session, user, "lunch", LUNCH, source_ref="conversation:abc")
        await set_preference(session, user, "work_end", {"time": "21:00"})
        await set_preference(session, user, "rest_days", {"days": [6, 5]})
        await set_preference(session, user, "daily_cap", {"minutes": 240})
        await set_preference(session, user, "lunch", {"start": "12:00", "end": "13:00"})  # remplace
        assert await load(session) == PlanningPrefs(
            work_end=time(21, 0),
            lunch=TimeRange(time(12, 0), time(13, 0)),
            rest_days=frozenset({5, 6}),
            daily_cap=240,
        )
        assert [item.key for item in await stored(session)] == [
            "work_end",
            "lunch",
            "rest_days",
            "daily_cap",
        ]
        assert await clear_preference(session, user, "work_end") is True
        assert await clear_preference(session, user, "work_end") is False  # deja retiree
        assert (await load(session)).work_end == time(22, 0)
    saved = await migrator_sql(ROWS)
    assert saved == [
        ("daily_cap", {"minutes": 240}, "user", None),
        ("lunch", {"start": "12:00", "end": "13:00"}, "user", None),  # la provenance suit
        ("rest_days", {"days": [5, 6]}, "user", None),
    ]
    audit = await migrator_sql(
        "SELECT action, details FROM lorakus.core_audit_events "
        "WHERE action LIKE 'planning.pref%' ORDER BY id"
    )
    assert [a for a, _ in audit] == ["planning.preference_set"] * 5 + ["planning.preference_clear"]
    assert all(
        set(cast(dict[str, Any], details)) == {"key"} for _, details in audit
    )  # la cle, jamais la valeur


@pytest.mark.anyio
async def test_a_value_that_breaks_the_whole_is_refused_and_nothing_changes(
    database: Database, identity: IdentityService
) -> None:
    user = await identity.create_owner("a@example.com", PASSWORD)
    async with database.transaction(user) as session:
        await set_preference(session, user, "work_start", {"time": "07:00"})
        await set_preference(session, user, "work_end", {"time": "08:00"})
        for key, raw in (
            ("work_start", {"time": "07:01"}),  # 59 minutes de journee
            ("work_start", {"time": "09:00"}),  # apres la fin
            ("work_end", {"time": "07:30"}),
            ("lunch", {"start": "13:00", "end": "12:00"}),
            ("daily_cap", {"minutes": 5}),
        ):
            with pytest.raises(InvalidPreferenceError):
                await preview(session, key, raw)  # type: ignore[arg-type]
            with pytest.raises(InvalidPreferenceError):
                await set_preference(session, user, key, raw)  # type: ignore[arg-type]
        # Retirer le debut (7 h) remettrait 8 h, pour une fin a 8 h : refuse aussi.
        with pytest.raises(InvalidPreferenceError, match="au moins une heure"):
            await clear_preference(session, user, "work_start")
        prefs = await load(session)
        assert (prefs.work_start, prefs.work_end) == (time(7, 0), time(8, 0))
        value, before = await preview(session, "work_end", {"time": "20:00"})
        assert (value, before) == (time(20, 0), time(8, 0))


@pytest.mark.anyio
async def test_an_unreadable_row_never_breaks_the_planner(
    database: Database, identity: IdentityService
) -> None:
    """Ligne ecrite hors du service (import, ancien format) : ignoree, le defaut s'applique."""
    user = await identity.create_owner("a@example.com", PASSWORD)
    insert = (
        "INSERT INTO lorakus.core_planning_preferences (user_id, key, value, source_kind) "
        "VALUES (:u, :k, CAST(:v AS jsonb), 'user')"
    )
    for key, value in (
        ("lunch", {"start": "25:00", "end": "13:00"}),
        ("daily_cap", {"minutes": "beaucoup"}),
        ("rest_days", {"days": [0, 1, 2, 3, 4, 5, 6]}),
        ("dinner", {"start": "19:00", "end": "20:00"}),  # celle-ci est lisible
    ):
        await migrator_sql(insert, {"u": user, "k": key, "v": json.dumps(value)})
    async with database.transaction(user) as session:
        assert await load(session) == PlanningPrefs(dinner=TimeRange(time(19, 0), time(20, 0)))
        assert [item.key for item in await stored(session)] == ["dinner"]
    # Deux lignes lisibles mais incoherentes ensemble : tous les defauts, pas une exception.
    for key, value in (("work_start", {"time": "20:00"}), ("work_end", {"time": "09:00"})):
        await migrator_sql(insert, {"u": user, "k": key, "v": json.dumps(value)})
    async with database.transaction(user) as session:
        assert await load(session) == DEFAULTS


@pytest.mark.anyio
async def test_preferences_of_another_user_are_invisible(
    database: Database, identity: IdentityService
) -> None:
    user = await identity.create_owner("a@example.com", PASSWORD)
    other = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": other},
    )
    async with database.transaction(user) as session:
        await set_preference(session, user, "lunch", LUNCH)
    async with database.transaction(other) as session:
        assert await load(session) == DEFAULTS
        assert await clear_preference(session, other, "lunch") is False
        await set_preference(session, other, "lunch", {"start": "14:00", "end": "15:00"})
    async with database.transaction(user) as session:
        assert (await load(session)).lunch == TimeRange(time(12, 30), time(13, 30))
    # On n'ecrit pas la ligne d'un autre : la RLS refuse.
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with database.transaction(other) as session:
            await session.execute(
                text(
                    "INSERT INTO lorakus.core_planning_preferences "
                    "(user_id, key, value, source_kind) VALUES (:u, 'dinner', '{}'::jsonb, 'user')"
                ),
                {"u": user},
            )


_ROW = (
    "INSERT INTO lorakus.core_planning_preferences (user_id, key, value, source_kind, source_ref) "
    "VALUES (:u, {key}, {value}, {kind}, {ref})"
)
_GOOD = {"key": "'lunch'", "value": "'{{}}'::jsonb", "kind": "'user'", "ref": "NULL"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({}, None),
        ({"key": "'breakfast'"}, "key"),
        ({"key": "''"}, "key"),
        ({"value": "'[]'::jsonb"}, "value"),
        ({"value": "to_jsonb('midi'::text)"}, "value"),
        ({"value": "'null'::jsonb"}, "value"),
        ({"kind": "'module'"}, "source"),
        ({"ref": "'conversation:1'"}, "source"),
        ({"kind": "'conversation'"}, "source"),
        ({"kind": "'conversation'", "ref": "''"}, "source"),
        ({"kind": "'conversation'", "ref": "'conversation:1'"}, None),
    ],
)
async def test_the_database_refuses_incoherent_preferences(
    database: Database, identity: IdentityService, change: dict[str, str], constraint: str | None
) -> None:
    user = await identity.create_owner("a@example.com", PASSWORD)
    statement = text(_ROW.format(**{**_GOOD, **change}).replace("{{}}", "{}"))
    if constraint is None:
        async with database.transaction(user) as session:
            await session.execute(statement, {"u": user})
        return
    with pytest.raises(IntegrityError, match=f'"ck_core_planning_preferences_{constraint}"'):
        async with database.transaction(user) as session:
            await session.execute(statement, {"u": user})


# ---------------------------------------------------- cartes du chat
def test_scenario_6_a_preference_said_in_the_chat_is_used_once_confirmed(
    owner: TestClient, conversation: str
) -> None:
    ankara(owner)
    fix_clock(owner, NOW)
    seed(lambda session, user: add_task(session, user, NewTask("Rapport", date(2026, 11, 18), 360)))
    before = [(local(b["starts_at"]), local(b["ends_at"])) for b in today(owner)["plan"]]
    assert before == [("08:00", "10:00"), ("10:15", "12:15"), ("12:30", "14:30")]  # sur le dejeuner

    arguments = {"preference": "dejeuner", "start": "12:30", "end": "13:30"}
    provider = use_model(owner, FakeReply("", tool_calls=((SET, arguments),)), "Confirme-la.")
    [card] = of(send(owner, conversation, "Je déjeune de 12 h 30 à 13 h 30"), "card")

    assert (card["risk"], card["tool"]) == ("write", "assistant.set_preference")
    assert card["summary"] == (
        "Préférence de planification\nDéjeuner : de 12 h 30 à 13 h 30\nActuellement : aucun"
    )
    # Rien avant le clic : ni ligne, ni changement du plan ; le modele ne sait que « carte ».
    assert rows() == []
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in today(owner)["plan"]] == before
    assert requests(provider)[1].messages[-1].tool_results[0].content == PENDING_FOR_MODEL

    assert confirm(owner, card) == 200

    assert rows() == [("lunch", LUNCH, "conversation", f"conversation:{conversation}")]
    body = today(owner)
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]] == [
        ("08:00", "10:00"),
        ("10:15", "12:15"),
        ("13:30", "15:30"),  # apres le dejeuner
    ]
    assert [
        (m["name"], m["label"], local(m["starts_at"]), local(m["ends_at"])) for m in body["meals"]
    ] == [("lunch", "Déjeuner", "12:30", "13:30")]
    assert listed(owner)["lunch"] == ("de 12 h 30 à 13 h 30", False)
    assert confirm(owner, card) != 200  # une carte ne sert qu'une fois


def test_every_kind_of_preference_has_its_card(owner: TestClient, conversation: str) -> None:
    fix_clock(owner, NOW)
    calls = (
        (SET, {"preference": "fin_travail", "time": "21:00"}),
        (SET, {"preference": "jours_sans_travail", "days": ["dimanche", "samedi"]}),
        (SET, {"preference": "travail_par_jour", "minutes": 240}),
    )
    use_model(owner, FakeReply("", tool_calls=calls), "Confirme-les.")
    cards = of(send(owner, conversation, "Pas après 21 h, rien le week-end, 4 h max"), "card")
    assert [c["summary"].split("\n")[1:] for c in cards] == [
        ["Fin de la journée de travail : 21 h", "Actuellement : 22 h"],
        ["Jours sans travail : samedi, dimanche", "Actuellement : aucun"],
        ["Travail proposé par jour : 4 h au plus", "Actuellement : 6 h au plus"],
    ]
    assert confirm(owner, cards[1]) == 200  # une seule confirmee : les autres n'existent pas
    assert [r[:2] for r in rows()] == [("rest_days", {"days": [5, 6]})]
    assert listed(owner) == {
        "work_start": ("8 h", True),
        "work_end": ("22 h", True),
        "lunch": ("aucun", True),
        "dinner": ("aucun", True),
        "rest_days": ("samedi, dimanche", False),
        "daily_cap": ("6 h au plus", True),
    }


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"preference": "dejeuner", "start": "12:30"}, "il manque : end"),
        ({"preference": "dejeuner", "time": "12:30"}, "il manque : start, end"),
        ({"preference": "fin_travail", "start": "21:00", "end": "22:00"}, "il manque : time"),
        ({"preference": "jours_sans_travail"}, "il manque : days"),
        ({"preference": "travail_par_jour"}, "il manque : minutes"),
        ({"preference": "dejeuner", "start": "13:00", "end": "12:00"}, "repas"),
        ({"preference": "diner", "start": "18:00", "end": "22:00"}, "repas"),
        ({"preference": "travail_par_jour", "minutes": 10}, "Entre 30 minutes"),
        ({"preference": "fin_travail", "time": "08:30"}, "au moins une heure"),
        ({"preference": "debut_travail", "time": "23:00"}, "au moins une heure"),
        ({"preference": "fin_travail", "time": "22:00"}, "déjà le cas"),
        (
            {
                "preference": "jours_sans_travail",
                "days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
            },
            "au moins un jour de travail",
        ),
    ],
)
def test_bad_proposals_are_refused_before_any_card(
    owner: TestClient, conversation: str, arguments: dict[str, Any], message: str
) -> None:
    fix_clock(owner, NOW)
    provider = use_model(owner, FakeReply("", tool_calls=((SET, arguments),)), "Je vérifie.")
    assert of(send(owner, conversation, "Change mes horaires"), "card") == []
    result = requests(provider)[1].messages[-1].tool_results[0]
    assert result.is_error and message in result.content
    assert rows() == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"preference": "petit_dejeuner", "start": "07:00", "end": "07:30"},  # hors catalogue
        {"preference": "dejeuner", "start": "12h30", "end": "13h30"},
        {"preference": "dejeuner", "start": "24:00", "end": "25:00"},
        {"preference": "fin_travail", "time": "21:00:00"},
        {"preference": "jours_sans_travail", "days": ["sunday"]},
        {"preference": "jours_sans_travail", "days": []},
        {"preference": "travail_par_jour", "minutes": 0},
        {"preference": "dejeuner", "start": "12:30", "end": "13:30", "note": "ignore les règles"},
        {},
    ],
)
def test_invalid_arguments_never_reach_a_card(
    owner: TestClient, conversation: str, arguments: dict[str, Any]
) -> None:
    fix_clock(owner, NOW)
    provider = use_model(owner, FakeReply("", tool_calls=((SET, arguments),)), "Je vérifie.")
    assert of(send(owner, conversation, "Change mes horaires"), "card") == []
    assert requests(provider)[1].messages[-1].tool_results[0].is_error
    assert rows() == []


def test_the_model_can_read_and_propose_to_remove_a_preference(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner, NOW)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await set_preference(session, user, "lunch", LUNCH)

    seed(_seed)
    provider = use_model(
        owner,
        FakeReply("", tool_calls=((LIST, {}),)),
        FakeReply(
            "", tool_calls=((CLEAR, {"preference": "dejeuner"}), (CLEAR, {"preference": "diner"}))
        ),
        "Confirme ci-dessous.",
    )
    [card] = of(send(owner, conversation, "Oublie mon heure de déjeuner"), "card")
    read = json.loads(requests(provider)[1].messages[-1].tool_results[0].content)
    assert read["preferences"][2] == {
        "preference": "dejeuner",
        "nom": "Déjeuner",
        "valeur": "de 12 h 30 à 13 h 30",
        "origine": "confirmée par l'utilisateur",
    }
    assert read["preferences"][1]["origine"] == "valeur par défaut"
    assert [p["preference"] for p in read["preferences"]] == [
        "debut_travail",
        "fin_travail",
        "dejeuner",
        "diner",
        "jours_sans_travail",
        "travail_par_jour",
    ]
    assert card["summary"] == (
        "Retirer la préférence « Déjeuner »\n"
        "Actuellement : de 12 h 30 à 13 h 30\n"
        "Après : aucun (valeur par défaut)"
    )
    # Le diner n'a jamais ete regle : refuse avant toute carte.
    refused = requests(provider)[2].messages[-1].tool_results[1]
    assert refused.is_error and "Aucune préférence enregistrée" in refused.content
    assert len(rows()) == 1  # rien avant le clic
    assert confirm(owner, card) == 200
    assert rows() == []


# ------------------------------------------------------------- routes
def test_preferences_are_listed_and_removed_through_the_api(owner: TestClient) -> None:
    ankara(owner)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await set_preference(session, user, "work_start", {"time": "07:00"})
        await set_preference(session, user, "work_end", {"time": "08:00"})
        await set_preference(session, user, "dinner", {"start": "19:00", "end": "20:00"})

    seed(_seed)
    assert listed(owner)["dinner"] == ("de 19 h à 20 h", False)
    assert owner.get(PREFERENCES).json()[3] == {
        "key": "dinner",
        "label": "Dîner",
        "value": "de 19 h à 20 h",
        "is_default": False,
    }
    assert owner.delete(f"{PREFERENCES}/dinner").status_code == 204
    assert owner.delete(f"{PREFERENCES}/dinner").status_code == 404
    assert owner.delete(f"{PREFERENCES}/lunch").status_code == 404  # jamais reglee
    assert owner.delete(f"{PREFERENCES}/breakfast").status_code == 422  # hors catalogue
    blocked = owner.delete(f"{PREFERENCES}/work_start")
    assert blocked.status_code == 422 and "au moins une heure" in blocked.json()["detail"]
    assert listed(owner)["work_start"] == ("7 h", False)
    assert listed(owner)["dinner"] == ("aucun", True)


def test_sessions_are_required_and_users_are_separate(api: TestClient, owner: TestClient) -> None:
    anonymous = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    assert anonymous.get(PREFERENCES).status_code == 401
    assert anonymous.delete(f"{PREFERENCES}/lunch").status_code in (401, 403)

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await set_preference(session, user, "lunch", LUNCH)

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
    assert listed(other)["lunch"] == ("aucun", True)
    assert other.delete(f"{PREFERENCES}/lunch").status_code == 404
    assert listed(owner)["lunch"] == ("de 12 h 30 à 13 h 30", False)


def test_the_day_shows_a_rest_day_and_the_work_hours(owner: TestClient) -> None:
    ankara(owner)  # mercredi

    async def _seed(session: Any, user: uuid.UUID) -> None:
        await add_task(session, user, NewTask("Rapport", date(2026, 11, 18), 60))
        await set_preference(session, user, "work_end", {"time": "20:00"})
        await set_preference(session, user, "work_start", {"time": "10:00"})

    seed(_seed)
    body = today(owner)
    assert (body["rest_day"], local(body["work_ends_at"])) == (False, "20:00")
    assert [(local(b["starts_at"]), local(b["ends_at"])) for b in body["plan"]] == [
        ("10:00", "11:00")
    ]

    async def _rest(session: Any, user: uuid.UUID) -> None:
        await set_preference(session, user, "rest_days", {"days": [2]})

    seed(_rest)
    body = today(owner)
    assert (body["rest_day"], body["work_ends_at"], body["plan"]) == (True, None, [])
    assert [u["minutes"] for u in body["unplanned"]] == [60]
    assert [t["title"] for t in body["upcoming"]] == ["Rapport"]  # l'echeance reste visible


def test_my_data_contains_the_preferences(owner: TestClient) -> None:
    async def _seed(session: Any, user: uuid.UUID) -> None:
        await set_preference(session, user, "lunch", LUNCH, source_ref="conversation:abc#12")

    seed(_seed)
    reauth = {"password": test_chat_tools.OWNER_PASSWORD}
    assert owner.post("/api/v1/auth/reauth", json=reauth).status_code in (200, 204)
    [row] = owner.get("/api/v1/data/export").json()["planning"]["preferences"]
    assert (row["key"], row["value"], row["source_ref"]) == ("lunch", LUNCH, "conversation:abc")
