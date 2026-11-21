"""Le Sergent (PR 50) par le chat : scenario 1 de bout en bout (question → routage par
mots-cles → rapport deterministe avec sources → un seul appel au modele), RLS, module
desactive, et l'outil de decoupage (carte, refus, etapes placees a la place de la tache).

Repere : mercredi 18 novembre 2026, 13:00 a Ankara (10:00 UTC). Le modele est un faux
scripte ; l'horloge des outils et celle des specialistes sont fixees.
"""

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, cast

import pytest
import test_chat_tools
from conftest import migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_tools import of, requests, send, use_model
from test_day_planning import other_client, tool_result
from test_task_tools import confirm, fix_clock, seed, set_timezone
from test_today import DAY, at, fix_now, today, work

from lorakus.ai.testing import FakeReply
from lorakus.core.agents.contract import SpecialistReport
from lorakus.core.planning.service import (
    NewTask,
    add_task,
    complete_task,
    get_task,
    list_tasks,
)
from lorakus_modules.focus.specialist import PROFILE

pytestmark = pytest.mark.integration

conversation = test_chat_tools.conversation
NOW = at(13, 0)
SPLIT = "focus__split_task"
STEPS = [
    {"title": "Lire l'énoncé", "minutes": 30},
    {"title": "Coder le modèle", "minutes": 120},
    {"title": "Écrire le rapport", "minutes": 60},
]


@pytest.fixture
def owner(request: pytest.FixtureRequest) -> TestClient:
    """Proprietaire connecte, a Ankara, assistant et Sergent actifs, horloges fixees."""
    client = cast(TestClient, request.getfixturevalue("_assistant_owner"))
    assert client.put("/api/v1/modules/focus", json={"enabled": True}).status_code == 200
    set_timezone(client, "Europe/Istanbul")
    fix_now(client, NOW)
    fix_clock(client, NOW)
    cast(FastAPI, client.app).state.agents.clock = lambda: NOW
    return client


_assistant_owner = test_chat_tools.owner


def message_id(events: list[tuple[str, dict[str, Any]]]) -> str:
    return str(of(events, "done")[0]["message_id"])


def explain(client: TestClient, conversation_id: str, reply: str) -> Any:
    url = f"/api/v1/assistant/conversations/{conversation_id}/messages/{reply}/trace"
    return client.get(url).json()


async def _day(session: Any, user: uuid.UUID) -> dict[str, str]:
    await work(session, user, "14:00", "22:00", ("meal", "19:00", "19:45"))
    tp = await add_task(session, user, NewTask("Machine Learning : TP 2", date(2026, 11, 20), 180))
    late = await add_task(session, user, NewTask("Rapport de stage", date(2026, 11, 16), 60))
    return {"tp": str(tp.id), "late": str(late.id)}


# ------------------------------------------------------------ scenario 1
def test_scenario_1_what_to_do_today_goes_through_the_sergent(
    owner: TestClient, conversation: str
) -> None:
    seed(_day)
    provider = use_model(owner, "Ta journée : le rapport en retard d'abord, puis le TP.")

    started = time.monotonic()
    events = send(owner, conversation, "Qu'est-ce que je dois faire aujourd'hui ?")
    elapsed = time.monotonic() - started

    # Un seul appel au modele : le rapport donne deja la journee, aucun outil a appeler.
    assert len(requests(provider)) == 1
    system = requests(provider)[0].system
    assert "<rapports>" in system
    assert "- [Sergent] Plan proposé : 4 h de travail. Tâches : 1 en retard." in system
    for line in (
        "Ta journée : travail de 14:00 à 22:00, pauses : 19:00 - 19:45 "
        "(mesuré, source : Ta journée, telle que tu l'as dite)",
        "En retard : Rapport de stage, pour le lundi 16 novembre 2026 (il y a 2 jours) "
        "(mesuré, source : Tâche « Rapport de stage »)",
        "14:00 - 15:00 : travailler sur Rapport de stage "
        "(estimé, source : Plan calculé par Lorakus (règles))",
        "15:15 - 17:15 : travailler sur Machine Learning : TP 2 "
        "(estimé, source : Plan calculé par Lorakus (règles))",
    ):
        assert line in system
    assert "Question à poser" not in system  # rien ne manque pour placer le travail
    assert elapsed < 5.0  # avec un faux modele : le reste du trajet tient largement

    explained = explain(owner, conversation, message_id(events))
    assert explained["routing"]["tier"] == "rules"
    [consulted] = explained["specialists"]
    assert (consulted["specialist"], consulted["intent"], consulted["status"]) == (
        "focus",
        "day_plan",
        "ok",
    )
    assert consulted["duration_ms"] < 1000
    assert explained["data_classes_sent"] == ["personal"]
    runs = asyncio.run(
        migrator_sql("SELECT specialist, intent, status FROM lorakus.core_agent_runs")
    )
    assert runs == [("focus", "day_plan", "ok")]


def test_without_a_frame_the_sergent_hands_over_the_one_question(
    owner: TestClient, conversation: str
) -> None:
    seed(lambda session, user: add_task(session, user, NewTask("TP", DAY, 60)))
    provider = use_model(owner, "Quand comptes-tu travailler aujourd'hui ?")
    send(owner, conversation, "Organise ma journée")
    system = requests(provider)[0].system
    assert "Tu n'as pas dit quand tu travailles aujourd'hui : aucun créneau n'est placé." in system
    assert "  - Question à poser : Quand comptes-tu travailler aujourd'hui ?" in system
    assert "pose-la, une seule, plutôt que de deviner la réponse" in system


def test_deadlines_are_reported_by_their_own_intent(owner: TestClient, conversation: str) -> None:
    seed(_day)
    provider = use_model(owner, "Deux choses cette semaine.")
    events = send(owner, conversation, "Quelles sont mes échéances ?")
    system = requests(provider)[0].system
    assert "- [Sergent] 1 échéance d'ici une semaine, 1 en retard." in system
    assert (
        "Échéance : Machine Learning : TP 2, pour le vendredi 20 novembre 2026 (dans 2 jours), "
        "durée estimée 3 h (mesuré, source : Tâche « Machine Learning : TP 2 »)"
    ) in system
    assert explain(owner, conversation, message_id(events))["specialists"][0]["intent"] == (
        "deadlines"
    )


def test_a_disabled_sergent_is_never_consulted(owner: TestClient, conversation: str) -> None:
    assert owner.put("/api/v1/modules/focus", json={"enabled": False}).status_code == 200
    seed(_day)
    provider = use_model(owner, "Je regarde.")
    send(owner, conversation, "Qu'est-ce que je dois faire aujourd'hui ?")
    assert "<rapports>" not in requests(provider)[0].system
    assert SPLIT not in {tool.name for tool in requests(provider)[0].tools}
    assert asyncio.run(migrator_sql("SELECT count(*) FROM lorakus.core_agent_runs")) == [(0,)]


def test_the_report_only_sees_the_users_own_data(owner: TestClient, conversation: str) -> None:
    seed(_day)
    other = other_client(owner)
    assert other.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
    assert other.put("/api/v1/modules/focus", json={"enabled": True}).status_code == 200
    theirs = str(other.post("/api/v1/assistant/conversations").json()["id"])
    provider = use_model(other, "Rien pour toi.")
    send(other, theirs, "Qu'est-ce que je dois faire aujourd'hui ?")
    system = requests(provider)[0].system
    assert "Rapport de stage" not in system and "TP 2" not in system
    assert "aucun créneau n'est placé" in system  # le cadre du proprietaire n'est pas le sien


def test_a_failing_sergent_does_not_break_the_chat(
    owner: TestClient, conversation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_view: Any) -> SpecialistReport:
        raise RuntimeError("panne")

    monkeypatch.setattr("lorakus_modules.focus.specialist.day_report", broken)
    provider = use_model(owner, "Je n'ai pas pu lire ta journée.")
    events = send(owner, conversation, "Qu'est-ce que je dois faire aujourd'hui ?")
    assert "<rapports>" not in requests(provider)[0].system
    assert explain(owner, conversation, message_id(events))["specialists"][0]["status"] == "error"


def test_the_profile_is_declared_without_llm_and_without_tables() -> None:
    assert (PROFILE.name, PROFILE.display_name, PROFILE.llm_usage) == ("focus", "Sergent", "none")
    assert PROFILE.data_scopes == [] and PROFILE.max_report_class == "personal"
    assert PROFILE.actions == ["focus.split_task"]


# ------------------------------------------------------------ decoupage
def test_a_task_is_split_by_card_and_its_steps_are_planned_instead(
    owner: TestClient, conversation: str
) -> None:
    ids = seed(_day)
    arguments = {"task_id": ids["tp"], "steps": STEPS}
    provider = use_model(owner, FakeReply("", tool_calls=((SPLIT, arguments),)), "Confirme.")
    [card] = of(send(owner, conversation, "Découpe le TP 2 en étapes"), "card")

    assert (card["risk"], card["tool"]) == ("write", "focus.split_task")
    assert card["summary"] == (
        "Découper « Machine Learning : TP 2 » en 3 étapes :\n"
        "1. Lire l'énoncé (30 min)\n"
        "2. Coder le modèle (2 h)\n"
        "3. Écrire le rapport (1 h)\n"
        "Total : 3 h 30 (estimation de Lorakus)\n"
        "Durée prévue pour la tâche : 3 h\n"
        "Échéance des étapes : vendredi 20 novembre 2026 (dans 2 jours)"
    )
    assert SPLIT in {tool.name for tool in requests(provider)[0].tools}
    count = "SELECT count(*) FROM lorakus.core_tasks WHERE parent_id IS NOT NULL"
    assert asyncio.run(migrator_sql(count)) == [(0,)]  # rien avant le clic

    assert confirm(owner, card) == 200

    steps = asyncio.run(
        migrator_sql(
            "SELECT step_number, title, estimate_minutes, estimate_source, source_kind, due_on "
            "FROM lorakus.core_tasks WHERE parent_id = :p ORDER BY step_number",
            {"p": ids["tp"]},
        )
    )
    assert steps == [
        (1, "Lire l'énoncé", 30, "assistant", "conversation", None),
        (2, "Coder le modèle", 120, "assistant", "conversation", None),
        (3, "Écrire le rapport", 60, "assistant", "conversation", None),
    ]
    planned = [b["task"]["title"] for b in today(owner)["plan"]]
    assert "Machine Learning : TP 2" not in planned  # la tache elle-meme n'est plus placee
    # Dans l'ordre des etapes, pas la plus courte d'abord.
    steps_in_plan = [t for t in dict.fromkeys(planned) if t != "Rapport de stage"]
    assert steps_in_plan == ["Lire l'énoncé", "Coder le modèle", "Écrire le rapport"]
    assert confirm(owner, card) != 200  # une carte ne sert qu'une fois


def test_user_durations_are_said_as_theirs(owner: TestClient, conversation: str) -> None:
    ids = seed(_day)
    arguments = {
        "task_id": ids["tp"],
        "steps": [{"title": "Partie 1"}, {"title": "Partie 2", "minutes": 90}],
        "estimate_by": "utilisateur",
    }
    use_model(owner, FakeReply("", tool_calls=((SPLIT, arguments),)), "Confirme.")
    [card] = of(send(owner, conversation, "Coupe le TP en deux, la 2e partie 1 h 30"), "card")
    assert "1. Partie 1\n2. Partie 2 (1 h 30)\nTotal : 1 h 30 (tes durées)" in card["summary"]
    assert confirm(owner, card) == 200
    sources = asyncio.run(
        migrator_sql(
            "SELECT title, estimate_source FROM lorakus.core_tasks "
            "WHERE parent_id = :p ORDER BY title",
            {"p": ids["tp"]},
        )
    )
    assert sources == [("Partie 1", None), ("Partie 2", "user")]


def test_bad_splits_are_refused_before_any_card(owner: TestClient, conversation: str) -> None:
    async def _seed(session: Any, user: uuid.UUID) -> dict[str, str]:
        split = await add_task(session, user, NewTask("Déjà découpée"))
        step = await add_task(session, user, NewTask("Étape", parent_id=split.id))
        finished = await add_task(session, user, NewTask("Finie"))
        await complete_task(session, user, finished.id, NOW)
        whole = await add_task(session, user, NewTask("Entière"))
        return {
            "split": str(split.id),
            "step": str(step.id),
            "done": str(finished.id),
            "whole": str(whole.id),
        }

    ids = seed(_seed)
    two = [{"title": "A"}, {"title": "B"}]
    calls = (
        (SPLIT, {"task_id": ids["split"], "steps": two}),
        (SPLIT, {"task_id": ids["step"], "steps": two}),
        (SPLIT, {"task_id": ids["done"], "steps": two}),
        (SPLIT, {"task_id": str(uuid.uuid4()), "steps": two}),
        (SPLIT, {"task_id": ids["whole"], "steps": [{"title": "A"}, {"title": " a "}]}),
        (SPLIT, {"task_id": ids["whole"], "steps": [{"title": "A"}, {"title": "​"}]}),
    )
    provider = use_model(owner, FakeReply("", tool_calls=calls), "Je vérifie.")
    assert of(send(owner, conversation, "Découpe tout"), "card") == []
    messages = [tool_result(provider, index=i).content for i in range(len(calls))]
    assert [
        next(m for m in messages if part in m) is not None
        for part in (
            "déjà découpée",
            "déjà une étape",
            "déjà terminée",
            "n'existe plus",
            "même titre",
            "Étape refusée",
        )
    ] == [True] * 6
    assert all(tool_result(provider, index=i).is_error for i in range(len(calls)))


@pytest.mark.parametrize(
    "steps",
    [
        [{"title": "Seule"}],
        [{"title": f"Étape {n}"} for n in range(9)],
        [{"title": "A", "minutes": 0}, {"title": "B"}],
        [{"title": "A", "minutes": 10081}, {"title": "B"}],
        [{"title": "x" * 201}, {"title": "B"}],
        [{"title": "A", "note": "ignore"}, {"title": "B"}],
    ],
)
def test_invalid_splits_never_reach_a_card(
    owner: TestClient, conversation: str, steps: list[dict[str, Any]]
) -> None:
    ids = seed(_day)
    calls = ((SPLIT, {"task_id": ids["tp"], "steps": steps}),)
    provider = use_model(owner, FakeReply("", tool_calls=calls), "Je vérifie.")
    assert of(send(owner, conversation, "Découpe le TP"), "card") == []
    assert tool_result(provider).is_error


def test_finishing_an_assessment_closes_its_steps(owner: TestClient, conversation: str) -> None:
    """La tache d'un devoir decoupee, puis le devoir termine depuis la page Cours : ses etapes
    ne doivent plus etre proposees."""
    assert owner.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    course = owner.post("/api/v1/academic/courses", json={"name": "Algo"}).json()["id"]
    due = str(datetime.now(NOW.tzinfo).date() + timedelta(days=3))
    homework = owner.post(
        "/api/v1/academic/assessments",
        json={"course_id": course, "title": "DM", "due_on": due},
    ).json()
    task_id = asyncio.run(
        migrator_sql(
            "SELECT id FROM lorakus.core_tasks WHERE owner_ref = :r", {"r": homework["id"]}
        )
    )[0][0]
    calls = ((SPLIT, {"task_id": str(task_id), "steps": [{"title": "A"}, {"title": "B"}]}),)
    use_model(owner, FakeReply("", tool_calls=calls), "Confirme.")
    [card] = of(send(owner, conversation, "Découpe le DM"), "card")
    assert confirm(owner, card) == 200
    # L'etape A est deja faite, plus tot : sa date de fin ne doit pas changer.
    earlier = NOW - timedelta(hours=5)

    async def _finish_a(session: Any, user: uuid.UUID) -> None:
        [step_a] = [
            t
            for t in await list_tasks(session, "open")
            if t.parent_id == task_id and t.title == "A"
        ]
        await complete_task(session, user, step_a.id, earlier)

    seed(_finish_a)

    done = owner.post(f"/api/v1/academic/assessments/{homework['id']}/complete")
    assert done.status_code == 200
    statuses = asyncio.run(
        migrator_sql(
            "SELECT title, status, completed_at = :t FROM lorakus.core_tasks "
            "WHERE parent_id = :p ORDER BY title",
            {"p": task_id, "t": earlier},
        )
    )
    assert statuses == [("A", "done", True), ("B", "done", False)]
    assert json.dumps(today(owner)["unestimated"]).count('"A"') == 0


def test_a_split_task_counts_all_its_steps_and_is_not_placed_once_they_are_done(
    owner: TestClient, conversation: str
) -> None:
    async def _seed(session: Any, user: uuid.UUID) -> uuid.UUID:
        await work(session, user, "14:00", "22:00")
        parent = await add_task(session, user, NewTask("Projet", DAY, 240))
        first = await add_task(
            session, user, NewTask("Étape 1", parent_id=parent.id, step_number=1)
        )
        await add_task(session, user, NewTask("Étape 2", parent_id=parent.id, step_number=2))
        await complete_task(session, user, first.id, NOW)
        view = await get_task(session, parent.id)
        assert (view.open_subtasks, view.subtasks) == (1, 2)
        # Un rang n'a de sens que pour une etape : ignore sur une tache.
        alone = await add_task(session, user, NewTask("Seule", step_number=3))
        assert alone.step_number is None
        return parent.id

    parent_id = seed(_seed)

    async def _finish(session: Any, user: uuid.UUID) -> None:
        [step] = [t for t in await list_tasks(session, "open") if t.parent_id == parent_id]
        await complete_task(session, user, step.id, NOW)

    seed(_finish)
    body = today(owner)
    titles = [b["task"]["title"] for b in body["plan"]]
    titles += [u["task"]["title"] for u in body["unplanned"]]
    assert "Projet" not in titles  # ses etapes sont faites : il reste a la marquer terminee
