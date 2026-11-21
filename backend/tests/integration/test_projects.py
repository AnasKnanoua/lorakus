"""Module projects (PR 51) par l'API et dans le chat : boite d'idees, projets, taches de projet
(chacune dans le planning du Core), projets qui dorment, cartes du chat, et le critere de bout
en bout : terminer la tache depuis le chat termine la tache du projet (evenement du worker).

Repere : mercredi 18 novembre 2026, 10:00 UTC (13:00 a Ankara). L'horloge des routes du module
(`get_now`) et celle des outils sont fixees.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import test_chat_tools
from conftest import migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_academic_api import deliver_events, other_user
from test_chat_tools import of, requests, send, use_model
from test_day_planning import tool_result
from test_task_tools import confirm, fix_clock, seed, set_timezone

from lorakus.ai.testing import FakeReply
from lorakus.core.events.bus import bus
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.planning.service import TASK_COMPLETED, TASK_ESTIMATED, ModuleTasks, complete_task
from lorakus.core.tools.inert import SAFE_GT, SAFE_LT
from lorakus_modules.projects import router as projects_router
from lorakus_modules.projects import service as projects_service
from lorakus_modules.projects.service import IDLE_DAYS, MAX_ACTIVE_PROJECTS, name_key

pytestmark = pytest.mark.integration

conversation = test_chat_tools.conversation
BASE = "/api/v1/projects"
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
LIST = "projects__list"
IDEA = "projects__add_idea"
PROJECT = "projects__add_project"
TASK = "projects__add_task"


@pytest.fixture
def owner(request: pytest.FixtureRequest) -> TestClient:
    """Proprietaire connecte, a Ankara, assistant et projets actifs, horloges fixees."""
    client = cast(TestClient, request.getfixturevalue("_assistant_owner"))
    assert client.put("/api/v1/modules/projects", json={"enabled": True}).status_code == 200
    set_timezone(client, "Europe/Istanbul")
    at(client, NOW)
    fix_clock(client, NOW)
    return client


_assistant_owner = test_chat_tools.owner


def at(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[projects_router.get_now] = lambda: now


def test_the_module_listens_to_completed_tasks_only() -> None:
    ModuleRegistry.from_entry_points()  # la decouverte importe le manifeste, donc les abonnements
    assert "projects.task_completed" in bus.handlers_for(TASK_COMPLETED)
    assert "projects.task_completed" not in bus.handlers_for(TASK_ESTIMATED)


def idea(client: TestClient, text: str = "Une appli pour réviser") -> dict[str, Any]:
    response = client.post(f"{BASE}/ideas", json={"text": text})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def project(client: TestClient, name: str = "Lorakus", **more: Any) -> dict[str, Any]:
    response = client.post(f"{BASE}/projects", json={"name": name, **more})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def add_task(client: TestClient, project_id: str, title: str = "README", **more: Any) -> Any:
    return client.post(f"{BASE}/projects/{project_id}/tasks", json={"title": title, **more})


def projects(client: TestClient, state: str = "active") -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], client.get(f"{BASE}/projects?state={state}").json())


def planning_rows() -> list[tuple[Any, ...]]:
    return asyncio.run(
        migrator_sql(
            "SELECT title, status, due_on, estimate_minutes, owner_ref FROM lorakus.core_tasks "
            "WHERE owner_module = 'projects' ORDER BY title"
        )
    )


# ------------------------------------------------------------------ idees
def test_ideas_are_noted_archived_and_deleted(owner: TestClient) -> None:
    first = idea(owner, "  Une appli\u200b pour   réviser  ")
    assert first["text"] == "Une appli pour réviser" and first["status"] == "inbox"
    second = idea(owner, "Bot Discord pour le club")
    assert [i["text"] for i in owner.get(f"{BASE}/ideas").json()] == [
        "Bot Discord pour le club",
        "Une appli pour réviser",
    ]
    for text in ("une APPLI pour réviser", "\u200b", " "):
        assert owner.post(f"{BASE}/ideas", json={"text": text}).status_code == 422
    assert owner.post(f"{BASE}/ideas", json={"text": "x" * 501}).status_code == 422

    assert owner.post(f"{BASE}/ideas/{first['id']}/archive").json()["status"] == "archived"
    assert owner.post(f"{BASE}/ideas/{first['id']}/archive").status_code == 422
    assert [i["id"] for i in owner.get(f"{BASE}/ideas?state=archived").json()] == [first["id"]]
    idea(owner, "Une appli pour réviser")  # archivee : la meme idee peut revenir

    assert owner.delete(f"{BASE}/ideas/{second['id']}").status_code == 204
    assert owner.delete(f"{BASE}/ideas/{second['id']}").status_code == 404
    assert owner.post(f"{BASE}/ideas/{uuid.uuid4()}/archive").status_code == 404


def test_an_idea_becomes_a_project_and_leaves_the_box(owner: TestClient) -> None:
    noted = idea(owner, "Site pour le centre de contrôle technique")
    created = project(owner, "Site du garage", idea_id=noted["id"])
    assert created["description"] == "Site pour le centre de contrôle technique"
    assert owner.get(f"{BASE}/ideas").json() == []
    # Une description donnee l'emporte ; une idee deja utilisee n'existe plus.
    other = idea(owner, "Autre idée")
    kept = project(owner, "Autre", description="Mon but", idea_id=other["id"])
    assert kept["description"] == "Mon but"
    again = owner.post(f"{BASE}/projects", json={"name": "Encore", "idea_id": other["id"]})
    assert again.status_code == 404
    archived = idea(owner, "Archivée")
    owner.post(f"{BASE}/ideas/{archived['id']}/archive")
    refused = owner.post(f"{BASE}/projects", json={"name": "Nope", "idea_id": archived["id"]})
    assert refused.status_code == 422 and "archivée" in refused.json()["detail"]
    assert sorted(p["name"] for p in projects(owner)) == ["Autre", "Site du garage"]


# --------------------------------------------------------------- projets
def test_project_names_are_unique_and_active_projects_limited(owner: TestClient) -> None:
    project(owner, "Lorakus")
    for name in ("lorakus", "LORAKUS", "  Lörakus "):
        refused = owner.post(f"{BASE}/projects", json={"name": name})
        assert refused.status_code == 422, name
    assert name_key("  Lörakus  ") == "lorakus"
    for n in range(MAX_ACTIVE_PROJECTS - 1):
        project(owner, f"Projet {n}")
    full = owner.post(f"{BASE}/projects", json={"name": "Un de trop"})
    assert full.status_code == 422 and "termines-en un" in full.json()["detail"]
    owner.post(f"{BASE}/projects/{projects(owner)[0]['id']}/finish")
    project(owner, "Un de trop")  # un projet termine libere une place


def test_open_tasks_are_limited_per_project(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(projects_service, "MAX_OPEN_TASKS", 2)
    lorakus = project(owner, "Lorakus")
    assert add_task(owner, lorakus["id"], "Un").status_code == 201
    assert add_task(owner, lorakus["id"], "Deux").status_code == 201
    full = add_task(owner, lorakus["id"], "Trois")
    assert full.status_code == 422 and "2 tâches ouvertes au plus" in full.json()["detail"]
    first = projects(owner)[0]["tasks"][0]["id"]
    owner.post(f"{BASE}/tasks/{first}/complete")
    assert add_task(owner, lorakus["id"], "Trois").status_code == 201  # une tache finie libere


def test_project_tasks_live_in_the_planning(owner: TestClient) -> None:
    lorakus = project(owner, "Lorakus")
    body = add_task(
        owner, lorakus["id"], "Écrire le README", due_on="2026-11-17", estimate_minutes=90
    )
    assert body.status_code == 201, body.text
    [task] = body.json()["tasks"]
    assert (task["title"], task["due_on"], task["overdue"], task["estimate_minutes"]) == (
        "Écrire le README",
        "2026-11-17",
        True,  # en retard a Ankara le 18
        90,
    )
    add_task(owner, lorakus["id"], "Déployer")
    assert planning_rows() == [
        ("Lorakus : Déployer", "open", None, None, planning_rows()[0][4]),
        ("Lorakus : Écrire le README", "open", datetime(2026, 11, 17).date(), 90, task["id"]),
    ]
    for wrong in (
        {"title": "écrire le README"},  # doublon ouvert
        {"title": "x", "due_on": "2040-01-01"},
        {"title": "\u200b"},
        {"title": "x", "estimate_minutes": 0},
    ):
        assert add_task(owner, lorakus["id"], **wrong).status_code == 422, wrong
    assert add_task(owner, str(uuid.uuid4())).status_code == 404


def test_finishing_tasks_and_projects_keeps_the_planning_right(owner: TestClient) -> None:
    lorakus = project(owner, "Lorakus")
    readme = add_task(owner, lorakus["id"], "README").json()["tasks"][0]
    add_task(owner, lorakus["id"], "Déployer")

    later = NOW + timedelta(hours=2)
    at(owner, later)
    done = owner.post(f"{BASE}/tasks/{readme['id']}/complete", json={"actual_minutes": 50})
    assert done.status_code == 200
    assert (done.json()["open_tasks"], done.json()["done_tasks"]) == (1, 1)
    assert datetime.fromisoformat(done.json()["last_activity_at"]) == later
    assert owner.post(f"{BASE}/tasks/{readme['id']}/complete").status_code == 422
    stored = asyncio.run(
        migrator_sql(
            "SELECT status, actual_minutes FROM lorakus.core_tasks WHERE owner_ref = :r",
            {"r": readme["id"]},
        )
    )
    assert stored == [("done", 50)]

    finished = owner.post(f"{BASE}/projects/{lorakus['id']}/finish")
    assert finished.status_code == 200
    assert finished.json()["status"] == "done" and finished.json()["open_tasks"] == 0
    assert {status for _, status, *_ in planning_rows()} == {"done"}
    assert owner.post(f"{BASE}/projects/{lorakus['id']}/finish").status_code == 422
    assert add_task(owner, lorakus["id"], "Encore").status_code == 422
    assert projects(owner) == [] and [p["name"] for p in projects(owner, "done")] == ["Lorakus"]


def test_deleting_removes_the_planning_tasks_too(owner: TestClient) -> None:
    lorakus = project(owner, "Lorakus")
    one = add_task(owner, lorakus["id"], "Un").json()["tasks"][0]
    add_task(owner, lorakus["id"], "Deux")
    assert owner.delete(f"{BASE}/tasks/{one['id']}").status_code == 204
    assert [t for t, *_ in planning_rows()] == ["Lorakus : Deux"]
    assert owner.delete(f"{BASE}/tasks/{one['id']}").status_code == 404
    assert owner.delete(f"{BASE}/projects/{lorakus['id']}").status_code == 204
    assert planning_rows() == [] and projects(owner) == []
    assert owner.delete(f"{BASE}/projects/{lorakus['id']}").status_code == 404


def test_a_project_without_activity_for_two_weeks_is_sleeping(owner: TestClient) -> None:
    lorakus = project(owner, "Lorakus")
    at(owner, NOW + timedelta(days=IDLE_DAYS - 1))
    assert projects(owner)[0]["idle_days"] is None
    at(owner, NOW + timedelta(days=IDLE_DAYS))
    assert projects(owner)[0]["idle_days"] == IDLE_DAYS
    # Ajouter une tache, c'est avancer : il ne dort plus.
    add_task(owner, lorakus["id"], "Reprendre")
    assert projects(owner)[0]["idle_days"] is None
    # Le moins avance d'abord.
    at(owner, NOW + timedelta(days=30))
    project(owner, "Récent")
    assert [p["name"] for p in projects(owner)] == ["Lorakus", "Récent"]
    owner.post(f"{BASE}/projects/{lorakus['id']}/finish")
    at(owner, NOW + timedelta(days=90))
    assert projects(owner, "done")[0]["idle_days"] is None  # un projet termine ne dort pas


def test_a_task_finished_from_the_chat_finishes_the_project_task(owner: TestClient) -> None:
    lorakus = project(owner, "Lorakus")
    task = add_task(owner, lorakus["id"], "README").json()["tasks"][0]
    finished_at = NOW + timedelta(days=20)

    async def _finish(session: Any, user: uuid.UUID) -> None:
        planned = await ModuleTasks("projects").get(session, task["id"])
        assert planned is not None
        await complete_task(session, user, planned.id, finished_at)

    seed(_finish)
    assert deliver_events() == (1, 0)
    at(owner, finished_at + timedelta(days=1))
    [body] = projects(owner)
    assert (body["open_tasks"], body["done_tasks"], body["idle_days"]) == (0, 1, None)
    assert datetime.fromisoformat(body["tasks"][0]["completed_at"]) == finished_at
    assert deliver_events() == (0, 0)  # rien a rejouer


def test_forged_or_foreign_events_change_nothing(owner: TestClient) -> None:
    from lorakus.core.events.bus import publish
    from lorakus.core.planning.service import TASK_COMPLETED

    lorakus = project(owner, "Lorakus")
    task = add_task(owner, lorakus["id"], "README").json()["tasks"][0]

    async def _forge(session: Any, user: uuid.UUID) -> None:
        for payload in (
            {"owner_module": "projects", "owner_ref": task["id"]},  # tache encore ouverte
            {"owner_module": "projects", "owner_ref": "pas-un-uuid"},
            {"owner_module": "projects", "owner_ref": str(uuid.uuid4())},
            {"owner_module": "academic", "owner_ref": task["id"]},
        ):
            await publish(session, TASK_COMPLETED, payload, user_id=user)

    seed(_forge)
    assert deliver_events() == (4, 0)
    assert projects(owner)[0]["open_tasks"] == 1


def test_another_user_sees_and_touches_nothing(owner: TestClient) -> None:
    mine = project(owner, "Lorakus")
    task = add_task(owner, mine["id"]).json()["tasks"][0]
    noted = idea(owner)
    other = other_user(owner)
    assert other.put("/api/v1/modules/projects", json={"enabled": True}).status_code == 200
    assert projects(other) == [] and other.get(f"{BASE}/ideas").json() == []
    for call in (
        lambda: add_task(other, mine["id"]),
        lambda: other.post(f"{BASE}/projects/{mine['id']}/finish"),
        lambda: other.delete(f"{BASE}/projects/{mine['id']}"),
        lambda: other.post(f"{BASE}/tasks/{task['id']}/complete"),
        lambda: other.delete(f"{BASE}/tasks/{task['id']}"),
        lambda: other.post(f"{BASE}/ideas/{noted['id']}/archive"),
        lambda: other.delete(f"{BASE}/ideas/{noted['id']}"),
        lambda: other.post(f"{BASE}/projects", json={"name": "X", "idea_id": noted["id"]}),
    ):
        assert call().status_code == 404
    project(other, "Lorakus")  # meme nom, autre utilisateur : permis
    assert [p["open_tasks"] for p in projects(owner)] == [1]


def test_routes_and_tools_ignore_a_disabled_module(owner: TestClient, conversation: str) -> None:
    project(owner, "Lorakus")
    assert owner.put("/api/v1/modules/projects", json={"enabled": False}).status_code == 200
    for path in ("projects", "ideas"):
        assert owner.get(f"{BASE}/{path}").status_code == 404
    provider = use_model(owner, FakeReply("", tool_calls=((IDEA, {"text": "x"}),)), "Non.")
    assert of(send(owner, conversation, "Note cette idée"), "card") == []
    assert IDEA not in [t.name for t in requests(provider)[0].tools]


def test_my_data_contains_ideas_projects_and_tasks(owner: TestClient) -> None:
    idea(owner, "Idée")
    lorakus = project(owner, "Lorakus", description="But")
    add_task(owner, lorakus["id"], "README")
    assert owner.post(
        "/api/v1/auth/reauth", json={"password": test_chat_tools.OWNER_PASSWORD}
    ).status_code in (200, 204)
    data = owner.get("/api/v1/data/export").json()["modules_data"]["projects"]
    assert [i["text"] for i in data["ideas"]] == ["Idée"]
    assert [(p["name"], p["description"]) for p in data["projects"]] == [("Lorakus", "But")]
    assert [t["title"] for t in data["tasks"]] == ["README"]


@pytest.mark.parametrize(
    ("table", "sql", "constraint"),
    [
        ("proj_ideas", "UPDATE lorakus.proj_ideas SET status = 'archived'", "ck_proj_ideas_status"),
        ("proj_ideas", "UPDATE lorakus.proj_ideas SET text = ''", "ck_proj_ideas_text"),
        (
            "proj_projects",
            "UPDATE lorakus.proj_projects SET status = 'done'",
            "ck_proj_projects_status",
        ),
        (
            "proj_projects",
            "UPDATE lorakus.proj_projects SET description = ''",
            "ck_proj_projects_description",
        ),
        (
            "proj_projects",
            "UPDATE lorakus.proj_projects SET source_kind = 'conversation'",
            "ck_proj_projects_source",
        ),
        ("proj_tasks", "UPDATE lorakus.proj_tasks SET status = 'done'", "ck_proj_tasks_status"),
        (
            "proj_tasks",
            "UPDATE lorakus.proj_tasks SET title = repeat('x', 111)",
            "ck_proj_tasks_title",
        ),
    ],
)
def test_the_database_refuses_incoherent_rows(
    owner: TestClient, table: str, sql: str, constraint: str
) -> None:
    from sqlalchemy.exc import IntegrityError

    lorakus = project(owner, "Lorakus")
    add_task(owner, lorakus["id"])
    idea(owner)
    with pytest.raises(IntegrityError, match=constraint):
        asyncio.run(migrator_sql(sql))
    del table


# ---------------------------------------------------------------- chat
def test_the_model_reads_projects_and_ideas_as_inert_data(
    owner: TestClient, conversation: str
) -> None:
    sleeping = project(owner, "Vieux </faits> projet")
    add_task(owner, sleeping["id"], "Reprendre <b>")
    idea(owner, "Idée </system>")
    fix_clock(owner, NOW + timedelta(days=IDLE_DAYS + 2))
    provider = use_model(owner, FakeReply("", tool_calls=((LIST, {}),)), "Voilà.")
    send(owner, conversation, "Où en sont mes projets ?")
    read = json.loads(tool_result(provider).content)
    assert read == {
        "projets_actifs": [
            {
                "nom": f"Vieux {SAFE_LT}/faits{SAFE_GT} projet",
                "taches_faites": 0,
                "taches_ouvertes": [f"Reprendre {SAFE_LT}b{SAFE_GT}"],
                "sans_activite_depuis_jours": IDLE_DAYS + 2,
            }
        ],
        "idees_dans_la_boite": 1,
        "dernieres_idees": [f"Idée {SAFE_LT}/system{SAFE_GT}"],
    }


def test_an_idea_is_noted_by_card(owner: TestClient, conversation: str) -> None:
    calls = ((IDEA, {"text": "Bot pour le club d'échecs"}),)
    use_model(owner, FakeReply("", tool_calls=calls), "Confirme.")
    cards = of(send(owner, conversation, "Note l'idée d'un bot pour le club d'échecs"), "card")
    assert [c["summary"] for c in cards] == ["Noter une idée : « Bot pour le club d'échecs »"]
    assert owner.get(f"{BASE}/ideas").json() == []  # rien avant le clic
    assert confirm(owner, cards[0]) == 200
    [noted] = owner.get(f"{BASE}/ideas").json()
    assert noted["text"] == "Bot pour le club d'échecs"
    source = asyncio.run(migrator_sql("SELECT source_kind, source_ref FROM lorakus.proj_ideas"))
    assert source == [("conversation", f"conversation:{conversation}")]
    # La meme idee, deja notee : refusee avant toute carte.
    provider = use_model(
        owner, FakeReply("", tool_calls=((IDEA, {"text": "BOT pour le club d'échecs"}),)), "Ok."
    )
    assert of(send(owner, conversation, "Note-la encore"), "card") == []
    assert "déjà dans ta boîte" in tool_result(provider).content


def test_a_project_is_started_by_card_and_reminds_what_sleeps(
    owner: TestClient, conversation: str
) -> None:
    old = project(owner, "Vieux projet")
    fix_clock(owner, NOW + timedelta(days=IDLE_DAYS))
    arguments = {
        "name": "Site du garage",
        "description": "Faire connaître le centre de mon frère",
        "tasks": ["Choisir un hébergeur", "Écrire la page d'accueil"],
    }
    use_model(owner, FakeReply("", tool_calls=((PROJECT, arguments),)), "Confirme.")
    [card] = of(send(owner, conversation, "Je lance le site du garage"), "card")
    assert card["summary"] == (
        "Commencer le projet « Site du garage »\n"
        "But : Faire connaître le centre de mon frère\n"
        "1. Choisir un hébergeur\n"
        "2. Écrire la page d'accueil\n"
        "Projets qui dorment : Vieux projet"
    )
    assert len(projects(owner)) == 1
    assert confirm(owner, card) == 200
    at(owner, NOW + timedelta(days=IDLE_DAYS))
    created = next(p for p in projects(owner) if p["name"] == "Site du garage")
    assert [t["title"] for t in created["tasks"]] == [
        "Choisir un hébergeur",
        "Écrire la page d'accueil",
    ]
    assert created["idle_days"] is None
    assert {t for t, *_ in planning_rows()} == {
        "Site du garage : Choisir un hébergeur",
        "Site du garage : Écrire la page d'accueil",
    }
    del old


def test_a_task_is_added_to_a_project_by_card(owner: TestClient, conversation: str) -> None:
    project(owner, "Lorakus")
    arguments = {
        "project": "lorakus",
        "title": "Écrire le README",
        "due_on": "2026-11-20",
        "estimate_minutes": 60,
    }
    use_model(owner, FakeReply("", tool_calls=((TASK, arguments),)), "Confirme.")
    [card] = of(send(owner, conversation, "Ajoute le README à Lorakus pour vendredi, 1 h"), "card")
    assert card["summary"] == (
        "Ajouter au projet « Lorakus » : « Écrire le README »\n"
        "Échéance : vendredi 20 novembre 2026 (dans 2 jours)\n"
        "Durée estimée : 1 h"
    )
    assert confirm(owner, card) == 200
    assert planning_rows()[0][:4] == (
        "Lorakus : Écrire le README",
        "open",
        datetime(2026, 11, 20).date(),
        60,
    )


def test_bad_proposals_are_refused_before_any_card(owner: TestClient, conversation: str) -> None:
    lorakus = project(owner, "Lorakus")
    add_task(owner, lorakus["id"], "README")
    done = project(owner, "Fini")
    owner.post(f"{BASE}/projects/{done['id']}/finish")
    calls = (
        (TASK, {"project": "Inconnu", "title": "x"}),
        (TASK, {"project": "Fini", "title": "x"}),
        (TASK, {"project": "Lorakus", "title": "readme"}),
        (TASK, {"project": "Lorakus", "title": "x", "due_on": "2026-11-17"}),
        (PROJECT, {"name": "LORAKUS"}),
        (PROJECT, {"name": "Nouveau", "tasks": ["A", "a"]}),
    )
    provider = use_model(owner, FakeReply("", tool_calls=calls), "Je vérifie.")
    assert of(send(owner, conversation, "Fais tout ça"), "card") == []
    messages = [tool_result(provider, index=i).content for i in range(len(calls))]
    for expected, message in zip(
        (
            "Aucun projet ne s'appelle",
            "terminé",
            "déjà ouverte",
            "déjà passée",
            "déjà un projet de ce nom",
            "même titre",
        ),
        messages,
        strict=True,
    ):
        assert expected in message, message


@pytest.mark.parametrize(
    "call",
    [
        (PROJECT, {"name": "A", "tasks": [f"T{n}" for n in range(9)]}),
        (PROJECT, {"name": "x" * 81}),
        (TASK, {"project": "Lorakus", "title": "x", "estimate_minutes": 0}),
        (IDEA, {"text": "x" * 501}),
        (IDEA, {"text": "x", "project": "y"}),
    ],
)
def test_invalid_arguments_never_reach_a_card(
    owner: TestClient, conversation: str, call: tuple[str, dict[str, Any]]
) -> None:
    project(owner, "Lorakus")
    provider = use_model(owner, FakeReply("", tool_calls=(call,)), "Je vérifie.")
    assert of(send(owner, conversation, "Vas-y"), "card") == []
    assert tool_result(provider).is_error
