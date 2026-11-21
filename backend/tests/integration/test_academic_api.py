"""Module academic (PR 46) par l'API et dans le chat : routes, carte de confirmation, et le
critere de la PR de bout en bout : terminer la tache (carte du chat) termine le devoir.

Le modele est un FakeProvider scripte ; l'heure vue par les outils est fixee (ToolPorts).
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import test_chat_tools
from conftest import BASE_URL, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD, of, requests, send, use_model
from test_task_tools import confirm, fix_clock, seed, set_timezone, tasks

from lorakus.ai.testing import FakeReply
from lorakus.core.events.bus import bus
from lorakus.core.events.relay import OutboxRelay
from lorakus.core.identity.passwords import HASHER
from lorakus.core.planning.service import NewTask, add_task
from lorakus.db.database import Database
from lorakus.settings import get_settings
from lorakus_modules.academic import tools as academic_tools
from lorakus_modules.assistant.service import ALREADY_PENDING_FOR_MODEL, PENDING_FOR_MODEL

pytestmark = pytest.mark.integration

conversation = test_chat_tools.conversation

BASE = "/api/v1/academic"
ADD = "academic__add_assessment"
LIST_TASKS = "assistant__list_tasks"
COMPLETE_TASK = "assistant__complete_task"
DELETE_TASK = "assistant__delete_task"
# Mercredi 18 novembre 2026, 22:30 UTC : 23:30 a Paris, deja jeudi 19 (01:30) a Ankara.
PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def owner(request: pytest.FixtureRequest) -> TestClient:
    """Proprietaire connecte, assistant et academic actifs."""
    client = cast(TestClient, request.getfixturevalue("_assistant_owner"))
    assert client.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    return client


_assistant_owner = test_chat_tools.owner


def today() -> date:
    return datetime.now(PARIS).date()  # fuseau par defaut du compte


def course(client: TestClient, name: str = "Machine Learning") -> str:
    response = client.post(f"{BASE}/courses", json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def assessment(client: TestClient, course_id: str, **more: Any) -> dict[str, Any]:
    body = {"course_id": course_id, "title": "TP 2", "due_on": str(today() + timedelta(days=2))}
    response = client.post(f"{BASE}/assessments", json={**body, **more})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def opened(client: TestClient) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], client.get(f"{BASE}/assessments").json())


def done(client: TestClient) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], client.get(f"{BASE}/assessments?state=done").json())


def deliver_events() -> tuple[int, int]:
    """Un tour du relais d'evenements, comme dans le worker."""

    async def _run() -> tuple[int, int]:
        db = Database.connect(get_settings())
        try:
            stats = await OutboxRelay(db, bus).run_once()
            return stats.delivered, stats.failed
        finally:
            await db.close()

    return asyncio.run(_run())


def other_user(client: TestClient) -> TestClient:
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'user')",
            {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
        )
    )
    other = TestClient(cast(FastAPI, client.app), base_url=BASE_URL)
    login = {"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    assert other.post("/api/v1/auth/login", json=login).status_code == 204
    assert other.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    return other


# ------------------------------------------------------------------ routes
def test_courses_and_assessments_through_the_api(owner: TestClient) -> None:
    ml = course(owner)
    assert owner.post(f"{BASE}/courses", json={"name": "machine learning"}).status_code == 422
    late = assessment(owner, ml, title="En retard", due_on=str(today() - timedelta(days=1)))
    soon = assessment(owner, ml, kind="exam", title="Partiel", weight=2.5, estimate_minutes=180)
    assert (late["overdue"], late["days_left"]) == (True, -1)  # la page accepte un devoir passe
    assert (soon["overdue"], soon["days_left"], soon["status"]) == (False, 2, "open")
    assert (soon["kind"], soon["weight"], soon["course_name"]) == ("exam", 2.5, "Machine Learning")
    assert [a["title"] for a in opened(owner)] == ["En retard", "Partiel"]
    assert owner.get(f"{BASE}/courses").json() == [
        {"id": ml, "name": "Machine Learning", "open_assessments": 2}
    ]
    assert [t["title"] for t in tasks(owner)] == [
        "Machine Learning : En retard",
        "Machine Learning : Partiel",
    ]

    moved = str(today() + timedelta(days=9))
    body = {"kind": "exam", "title": "Partiel final", "due_on": moved}
    changed = owner.put(f"{BASE}/assessments/{soon['id']}", json=body)
    assert changed.status_code == 200
    assert (changed.json()["title"], changed.json()["days_left"]) == ("Partiel final", 9)
    assert changed.json()["weight"] is None  # le formulaire envoie tout : absent = retire
    assert tasks(owner)[1]["title"] == "Machine Learning : Partiel final"
    assert tasks(owner)[1]["due_on"] == date.fromisoformat(moved)

    finished = owner.post(f"{BASE}/assessments/{late['id']}/complete")
    assert finished.status_code == 200
    assert (finished.json()["status"], finished.json()["overdue"]) == ("done", False)
    assert owner.post(f"{BASE}/assessments/{late['id']}/complete").status_code == 422
    assert [a["title"] for a in done(owner)] == ["En retard"]
    assert [t["title"] for t in tasks(owner, "done")] == ["Machine Learning : En retard"]

    assert owner.delete(f"{BASE}/assessments/{soon['id']}").status_code == 204
    assert opened(owner) == [] and tasks(owner) == []
    assert owner.delete(f"{BASE}/courses/{ml}").status_code == 204
    assert owner.get(f"{BASE}/courses").json() == [] and done(owner) == []
    assert tasks(owner, "done") == []


def test_bad_requests_are_refused_in_plain_words(owner: TestClient) -> None:
    ml = course(owner)
    soon = str(today() + timedelta(days=2))
    good = {"course_id": ml, "title": "TP", "due_on": soon}
    for change, code in (
        ({"title": ""}, 422),
        ({"title": "   "}, 422),
        ({"weight": 0}, 422),
        ({"weight": 100.5}, 422),
        ({"estimate_minutes": 0}, 422),
        ({"kind": "quiz"}, 422),
        ({"due_on": "vendredi"}, 422),
        ({"due_on": str(today() - timedelta(days=400))}, 422),
        ({"due_on": str(today() + timedelta(days=6 * 366))}, 422),
        ({"course_id": str(uuid.uuid4())}, 404),
        ({"unknown": 1}, 422),
    ):
        response = owner.post(f"{BASE}/assessments", json={**good, **change})
        assert response.status_code == code, change
    assert opened(owner) == [] and tasks(owner) == []
    blank = owner.post(f"{BASE}/assessments", json={**good, "title": "   "})
    assert blank.json()["detail"] == "Donne un titre à cette évaluation."
    assessment(owner, ml, title="TP", due_on=soon)
    again = owner.post(f"{BASE}/assessments", json={**good, "title": "tp"})
    assert again.status_code == 422
    assert again.json()["detail"] == "Cette évaluation existe déjà, avec la même échéance."
    # Corriger suit les memes regles que creer : date plausible, pas de doublon.
    other = assessment(owner, ml, title="Autre", due_on=soon)
    for change in (
        {"due_on": str(today() - timedelta(days=400))},
        {"due_on": str(today() + timedelta(days=6 * 366))},
        {"title": "tp"},
        {"weight": 0},
    ):
        body = {"title": "Autre", "due_on": soon, **change}
        assert owner.put(f"{BASE}/assessments/{other['id']}", json=body).status_code == 422
    assert [a["title"] for a in opened(owner)] == ["TP", "Autre"]
    assert [t["due_on"] for t in tasks(owner)] == [date.fromisoformat(soon)] * 2
    unknown = uuid.uuid4()
    body = {"title": "TP", "due_on": soon}
    assert owner.put(f"{BASE}/assessments/{unknown}", json=body).status_code == 404
    assert owner.post(f"{BASE}/assessments/{unknown}/complete").status_code == 404
    assert owner.delete(f"{BASE}/assessments/{unknown}").status_code == 404
    assert owner.delete(f"{BASE}/courses/{unknown}").status_code == 404


def test_today_follows_the_account_timezone(owner: TestClient) -> None:
    """Le retard se juge chez l'utilisateur, pas a l'heure du serveur.

    Kiritimati (UTC+14) et Pago Pago (UTC-11) : a toute heure, l'un des deux n'est pas au meme
    jour que UTC. Un « aujourd'hui » calcule en UTC echoue donc toujours pour l'un des deux.
    """
    ml = course(owner)
    days: dict[str, date] = {}
    for zone in ("Pacific/Pago_Pago", "Pacific/Kiritimati"):
        set_timezone(owner, zone)
        days[zone] = datetime.now(UTC).astimezone(ZoneInfo(zone)).date()
        created = assessment(owner, ml, title=zone, due_on=str(days[zone]))
        assert (created["overdue"], created["days_left"]) == (False, 0)  # a la creation
        seen = {a["title"]: a for a in opened(owner)}[zone]
        assert (seen["overdue"], seen["days_left"]) == (False, 0)  # et a la lecture
        moved = {"title": zone, "due_on": str(days[zone] + timedelta(days=1))}
        changed = owner.put(f"{BASE}/assessments/{created['id']}", json=moved).json()
        assert changed["days_left"] == 1
        back = {"title": zone, "due_on": str(days[zone])}
        assert owner.put(f"{BASE}/assessments/{created['id']}", json=back).status_code == 200
        extra = assessment(owner, ml, title=f"{zone} fini", due_on=str(days[zone]))
        ended = owner.post(f"{BASE}/assessments/{extra['id']}/complete").json()
        assert (ended["status"], ended["days_left"]) == ("done", 0)
    # Vu depuis Kiritimati, le devoir du jour de Pago Pago est deja en retard.
    gap = (days["Pacific/Pago_Pago"] - days["Pacific/Kiritimati"]).days
    assert gap in (-1, -2)
    west = {a["title"]: a for a in opened(owner)}["Pacific/Pago_Pago"]
    assert (west["overdue"], west["days_left"]) == (True, gap)
    finished = owner.post(f"{BASE}/assessments/{west['id']}/complete").json()
    assert (finished["overdue"], finished["days_left"]) == (False, gap)


def test_another_user_sees_and_touches_nothing(owner: TestClient) -> None:
    ml = course(owner)
    mine = assessment(owner, ml)
    other = other_user(owner)
    assert other.get(f"{BASE}/courses").json() == [] and opened(other) == []
    body = {"title": "x", "due_on": mine["due_on"]}
    for call in (
        lambda: other.post(f"{BASE}/assessments", json={**body, "course_id": ml}),
        lambda: other.put(f"{BASE}/assessments/{mine['id']}", json=body),
        lambda: other.post(f"{BASE}/assessments/{mine['id']}/complete"),
        lambda: other.delete(f"{BASE}/assessments/{mine['id']}"),
        lambda: other.delete(f"{BASE}/courses/{ml}"),
    ):
        assert call().status_code == 404
    assert [a["title"] for a in opened(owner)] == ["TP 2"]


def test_routes_and_tool_ignore_a_disabled_module(owner: TestClient, conversation: str) -> None:
    course(owner)
    assert owner.put("/api/v1/modules/academic", json={"enabled": False}).status_code == 200
    for path in ("courses", "assessments"):
        assert owner.get(f"{BASE}/{path}").status_code == 404
    provider = use_model(
        owner,
        FakeReply("", tool_calls=((ADD, {"course": "Algo", "due_on": "2099-01-01"}),)),
        "Je ne peux pas.",
    )
    events = send(owner, conversation, "Ajoute le devoir d'algo")
    assert of(events, "card") == []
    assert ADD not in [t.name for t in requests(provider)[0].tools]


def test_sessions_are_required(api: TestClient) -> None:
    assert api.get(f"{BASE}/courses").status_code == 401
    assert api.post(f"{BASE}/assessments", json={}).status_code in (401, 403)


def test_my_data_contains_courses_and_assessments(owner: TestClient) -> None:
    ml = course(owner)
    created = assessment(owner, ml, kind="exam", weight=2)
    owner.put("/api/v1/modules/academic", json={"enabled": False})  # donnees gardees
    reauth = {"password": test_chat_tools.OWNER_PASSWORD}
    assert owner.post("/api/v1/auth/reauth", json=reauth).status_code in (200, 204)
    exported = owner.get("/api/v1/data/export").json()["modules_data"]["academic"]
    assert exported["courses"] == [
        {"id": ml, "name": "Machine Learning", "created_at": exported["courses"][0]["created_at"]}
    ]
    [row] = exported["assessments"]
    assert (row["id"], row["course_id"], row["kind"]) == (created["id"], ml, "exam")
    assert (row["title"], row["due_on"], row["weight"]) == ("TP 2", created["due_on"], "2.00")
    assert (row["status"], row["source"], row["completed_at"]) == ("open", None, None)


# -------------------------------------------------- la carte du chat
NOW = datetime(2026, 11, 18, 22, 30, tzinfo=UTC)


def test_the_model_is_offered_the_tool_only_when_the_module_is_enabled(
    owner: TestClient, conversation: str
) -> None:
    provider = use_model(owner, "Bonjour.")
    send(owner, conversation, "Salut")
    assert ADD in [t.name for t in requests(provider)[0].tools]


def test_the_card_shows_the_absolute_date_and_nothing_is_added_without_a_click(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner, NOW)
    set_timezone(owner, "Europe/Istanbul")  # deja jeudi 19 a Ankara
    arguments = {
        "course": "Machine  Learning",
        "kind": "devoir",
        "due_on": "2026-11-20",
        "estimate_minutes": 180,
        "weight": 0.5,
    }
    provider = use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Confirme-la.")

    events = send(owner, conversation, "Ajoute le devoir de Machine Learning pour vendredi, 3 h")

    [card] = of(events, "card")
    assert card["risk"] == "write" and card["tool"] == "academic.add_assessment"
    assert card["summary"] == (
        "Ajouter un devoir : « Devoir »\n"
        "Cours : Machine Learning (nouveau cours)\n"
        "Échéance : vendredi 20 novembre 2026 (demain)\n"
        "Durée estimée : 3 h\n"
        "Coefficient : 0,5"
    )
    # Jamais d'ajout sans clic : ni cours, ni evaluation, ni tache ; le modele ne sait que
    # « carte affichee », jamais son identifiant.
    assert owner.get(f"{BASE}/courses").json() == [] and opened(owner) == []
    assert tasks(owner) == []
    result = requests(provider)[1].messages[-1].tool_results[0]
    assert result.content == PENDING_FOR_MODEL
    assert card["confirmation_id"] not in test_chat_tools.everything_sent(provider)

    assert confirm(owner, card) == 200

    [created] = opened(owner)
    assert (created["course_name"], created["title"], created["kind"]) == (
        "Machine Learning",
        "Devoir",
        "assignment",
    )
    assert (created["due_on"], created["estimate_minutes"], created["weight"]) == (
        "2026-11-20",
        180,
        0.5,
    )
    [task] = tasks(owner)
    assert task["title"] == "Machine Learning : Devoir"
    assert (task["due_on"], task["estimate"], task["source_kind"]) == (
        date(2026, 11, 20),
        180,
        "module",
    )
    rows = asyncio.run(migrator_sql("SELECT source_kind, source_ref FROM lorakus.acad_assessments"))
    assert rows == [("conversation", f"conversation:{conversation}")]
    assert confirm(owner, card) != 200  # une carte ne sert qu'une fois
    assert len(opened(owner)) == 1


def test_an_exam_in_a_known_course_reuses_the_course(owner: TestClient, conversation: str) -> None:
    fix_clock(owner, NOW)
    ml = course(owner, "Machine Learning")
    arguments = {
        "course": "machine learning",
        "kind": "examen",
        "title": "Partiel",
        "due_on": "2026-12-01",
    }
    use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Confirme-la.")
    [card] = of(send(owner, conversation, "J'ai le partiel de ML le 1er décembre"), "card")
    assert card["summary"] == (
        "Ajouter un examen : « Partiel »\n"
        "Cours : Machine Learning\n"  # le nom enregistre, pas celui du modele
        "Date : mardi 1 décembre 2026 (dans 13 jours)"
    )
    assert confirm(owner, card) == 200
    assert [c["id"] for c in owner.get(f"{BASE}/courses").json()] == [ml]  # pas de doublon
    assert [(a["kind"], a["course_id"]) for a in opened(owner)] == [("exam", ml)]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"course": "Algo", "due_on": "2026-11-18"}, "déjà passée"),  # mercredi : passe a Ankara
        ({"course": "Algo", "due_on": "2032-01-01"}, "trop lointaine"),
        ({"course": "​", "due_on": "2026-11-20"}, "Donne un nom"),
        ({"course": "Algo", "title": "​ ​", "due_on": "2026-11-20"}, "Donne un titre"),
    ],
)
def test_bad_proposals_are_refused_before_any_card(
    owner: TestClient, conversation: str, arguments: dict[str, Any], message: str
) -> None:
    fix_clock(owner, NOW)
    set_timezone(owner, "Europe/Istanbul")
    provider = use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Je vérifie.")
    events = send(owner, conversation, "Ajoute le devoir d'algo")
    assert of(events, "card") == []
    result = requests(provider)[1].messages[-1].tool_results[0]
    assert result.is_error and message in result.content
    assert owner.get(f"{BASE}/courses").json() == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"course": "Algo"},  # echeance obligatoire : le modele doit la demander
        {"course": "Algo", "due_on": "vendredi"},
        {"course": "Algo", "due_on": "2026-11-20", "weight": 0},
        {"course": "Algo", "due_on": "2026-11-20", "weight": 101},
        {"course": "Algo", "due_on": "2026-11-20", "estimate_minutes": 0},
        {"course": "Algo", "due_on": "2026-11-20", "kind": "quiz"},
        {"course": "Algo", "due_on": "2026-11-20", "summary": "Tout va bien"},
        {"course": "x" * 81, "due_on": "2026-11-20"},
    ],
)
def test_invalid_arguments_never_reach_a_card(
    owner: TestClient, conversation: str, arguments: dict[str, Any]
) -> None:
    fix_clock(owner, NOW)
    provider = use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Je vérifie.")
    assert of(send(owner, conversation, "Ajoute le devoir d'algo"), "card") == []
    assert requests(provider)[1].messages[-1].tool_results[0].is_error


def test_the_card_text_cannot_be_written_by_the_model(owner: TestClient, conversation: str) -> None:
    fix_clock(owner, NOW)
    arguments = {
        "course": "Algo\nÉchéance : demain‮",
        "title": "TP »\nCours : Autre\nCoefficient : 100",
        "due_on": "2026-11-25",
    }
    use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Voilà.")
    [card] = of(send(owner, conversation, "Ajoute le TP d'algo"), "card")
    lines = card["summary"].split("\n")
    # Trois lignes ecrites par le code ; le texte du modele reste entre guillemets, sur sa ligne.
    assert lines == [
        "Ajouter un devoir : « TP » Cours : Autre Coefficient : 100 »",
        "Cours : Algo Échéance : demain (nouveau cours)",
        "Échéance : mercredi 25 novembre 2026 (dans 7 jours)",
    ]


def test_an_assessment_already_open_shows_no_card(owner: TestClient, conversation: str) -> None:
    fix_clock(owner, NOW)
    arguments = {"course": "Algo", "title": "TP 2", "due_on": "2026-11-25"}
    again = FakeReply("", tool_calls=((ADD, arguments),))
    provider = use_model(owner, again, "Confirme.", again, "Elle attend.", again, "Déjà là.")
    [card] = of(send(owner, conversation, "Ajoute le TP 2 d'algo pour mercredi"), "card")
    # Le modele redemande la meme action alors que la carte attend : aucune nouvelle carte.
    assert of(send(owner, conversation, "Alors ?"), "card") == []
    waiting = requests(provider)[3].messages[-1].tool_results[0]
    assert waiting.content == ALREADY_PENDING_FOR_MODEL
    assert confirm(owner, card) == 200
    # Faite : la meme demande est refusee avant toute carte (casse ignoree par le service).
    assert of(send(owner, conversation, "Ajoute-le encore"), "card") == []
    refused = requests(provider)[5].messages[-1].tool_results[0]
    assert refused.is_error and "déjà dans tes cours" in refused.content
    assert len(opened(owner)) == 1 and len(tasks(owner)) == 1


def test_a_new_course_is_refused_before_the_card_when_courses_are_full(
    owner: TestClient, conversation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix_clock(owner, NOW)
    monkeypatch.setattr(academic_tools, "MAX_COURSES", 1)
    course(owner, "Algo")
    known = {"course": "algo", "due_on": "2026-11-25"}
    new = {"course": "Réseaux", "due_on": "2026-11-25"}
    provider = use_model(
        owner, FakeReply("", tool_calls=((ADD, new), (ADD, known))), "Une seule carte."
    )
    cards = of(send(owner, conversation, "Ajoute ces deux devoirs"), "card")
    assert [c["summary"].split("\n")[1] for c in cards] == ["Cours : Algo"]
    results = requests(provider)[1].messages[-1].tool_results
    assert results[0].is_error and "cours au plus" in results[0].content


def test_a_course_deleted_before_the_click_is_created_again_by_the_card(
    owner: TestClient, conversation: str
) -> None:
    """La carte dit « Cours : Algo » : le clic rend ce qu'elle annonce, meme si le cours a
    disparu entre-temps."""
    fix_clock(owner, NOW)
    algo = course(owner, "Algo")
    arguments = {"course": "Algo", "due_on": "2026-11-25"}
    use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Confirme.")
    [card] = of(send(owner, conversation, "Ajoute le devoir d'algo"), "card")
    assert owner.delete(f"{BASE}/courses/{algo}").status_code == 204
    assert confirm(owner, card) == 200
    assert [a["course_name"] for a in opened(owner)] == ["Algo"]


# --------------------- critere : terminer la tache termine le devoir
def test_completing_the_task_from_the_chat_completes_the_assessment(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner, NOW)
    ml = course(owner)
    homework = assessment(owner, ml, title="TP 2")
    other = assessment(owner, ml, title="TP 3")
    seed(lambda session, user: add_task(session, user, NewTask("Faire les courses")))
    listing = FakeReply("Je regarde.", tool_calls=((LIST_TASKS, {}),))
    provider = use_model(owner, listing, "Laquelle ?")
    send(owner, conversation, "Qu'est-ce que j'ai à faire ?")
    listed = requests(provider)[1].messages[-1].tool_results[0].content
    by_title = {t["titre"]: t for t in json.loads(listed)["taches"]}
    task = by_title["Machine Learning : TP 2"]
    assert task["module"] == "academic"  # le modele sait d'ou vient la tache

    use_model(
        owner,
        FakeReply(
            "",
            tool_calls=(
                (COMPLETE_TASK, {"task_id": task["id"]}),
                (DELETE_TASK, {"task_id": task["id"]}),
            ),
        ),
        "Confirme ci-dessous.",
    )
    cards = of(send(owner, conversation, "J'ai fini le TP 2 de ML"), "card")
    # Supprimer la tache d'un module depuis le chat est refuse avant toute carte (PR 44).
    assert [c["summary"] for c in cards] == ["Marquer comme terminée : « Machine Learning : TP 2 »"]
    assert deliver_events() == (0, 0)  # rien avant le clic
    assert {a["id"] for a in opened(owner)} == {homework["id"], other["id"]}

    assert confirm(owner, cards[0]) == 200
    assert deliver_events() == (1, 0)

    assert [a["id"] for a in opened(owner)] == [other["id"]]
    [finished] = done(owner)
    assert (finished["id"], finished["status"]) == (homework["id"], "done")
    assert datetime.fromisoformat(finished["completed_at"]) == NOW  # l'instant de la tache
    assert [c["open_assessments"] for c in owner.get(f"{BASE}/courses").json()] == [1]
    assert deliver_events() == (0, 0)  # livre une seule fois


# ------------------------------------------- duree et temps passe (PR 49)
def test_lorakus_can_propose_its_own_estimate_and_says_so(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner, NOW)
    set_timezone(owner, "Europe/Istanbul")
    arguments = {
        "course": "Algo",
        "due_on": "2026-11-20",
        "estimate_minutes": 150,
        "estimate_by": "lorakus",
    }
    use_model(owner, FakeReply("", tool_calls=((ADD, arguments),)), "Confirme-la.")
    [card] = of(send(owner, conversation, "Ajoute le DM d'algo, estime toi-même"), "card")
    assert "Durée estimée : 2 h 30 (estimation de Lorakus)" in card["summary"].split("\n")
    assert confirm(owner, card) == 200
    [created] = opened(owner)
    assert created["estimate_minutes"] == 150
    source = asyncio.run(
        migrator_sql(
            "SELECT estimate_source FROM lorakus.core_tasks WHERE owner_ref = :ref",
            {"ref": created["id"]},
        )
    )
    assert source == [("assistant",)]


def test_an_estimate_given_in_the_chat_reaches_the_assessment_page(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner, NOW)
    homework = assessment(owner, course(owner))
    assert homework["estimate_minutes"] is None
    task_id = asyncio.run(
        migrator_sql(
            "SELECT id FROM lorakus.core_tasks WHERE owner_ref = :ref", {"ref": homework["id"]}
        )
    )[0][0]
    arguments = {"task_id": str(task_id), "minutes": 180, "estimate_by": "utilisateur"}
    use_model(owner, FakeReply("", tool_calls=(("assistant__set_estimate", arguments),)), "Ok.")
    [card] = of(send(owner, conversation, "Le TP 2 me prendra 3 h"), "card")
    assert card["summary"] == ("Durée de « Machine Learning : TP 2 » : 3 h\nActuellement : aucune")
    assert confirm(owner, card) == 200
    assert deliver_events() == (1, 0)
    [updated] = opened(owner)
    assert updated["estimate_minutes"] == 180
    assert deliver_events() == (0, 0)


def test_the_time_spent_is_given_when_finishing_from_the_page(owner: TestClient) -> None:
    homework = assessment(owner, course(owner), estimate_minutes=120)
    refused = owner.post(
        f"{BASE}/assessments/{homework['id']}/complete", json={"actual_minutes": 0}
    )
    assert refused.status_code == 422
    extra = owner.post(
        f"{BASE}/assessments/{homework['id']}/complete", json={"actual_minutes": 90, "note": "x"}
    )
    assert extra.status_code == 422  # aucun champ inconnu
    finished = owner.post(
        f"{BASE}/assessments/{homework['id']}/complete", json={"actual_minutes": 150}
    )
    assert finished.status_code == 200, finished.text
    stored = asyncio.run(
        migrator_sql(
            "SELECT status, actual_minutes FROM lorakus.core_tasks WHERE owner_ref = :ref",
            {"ref": homework["id"]},
        )
    )
    assert stored == [("done", 150)]
    # Sans corps, comme avant : aucun temps note.
    other = assessment(owner, course(owner, "Algo"))
    assert owner.post(f"{BASE}/assessments/{other['id']}/complete").status_code == 200
    none = asyncio.run(
        migrator_sql(
            "SELECT actual_minutes FROM lorakus.core_tasks WHERE owner_ref = :ref",
            {"ref": other["id"]},
        )
    )
    assert none == [(None,)]


def test_the_handler_still_runs_when_the_module_is_disabled(owner: TestClient) -> None:
    """Desactiver ne supprime pas les donnees : elles restent justes au retour."""
    fix_clock(owner, NOW)
    homework = assessment(owner, course(owner))
    assert owner.put("/api/v1/modules/academic", json={"enabled": False}).status_code == 200

    async def _finish(session: Any, user: uuid.UUID) -> None:
        from lorakus.core.planning.service import ModuleTasks, complete_task

        task = await ModuleTasks("academic").get(session, homework["id"])
        assert task is not None
        await complete_task(session, user, task.id, NOW)

    seed(_finish)
    assert deliver_events() == (1, 0)
    assert owner.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    assert opened(owner) == [] and [a["id"] for a in done(owner)] == [homework["id"]]
