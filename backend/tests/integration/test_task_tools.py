"""Taches dans le chat (PR 44) : cartes avec date absolue, fuseau du compte, permissions.

Le modele est un FakeProvider scripte ; l'heure vue par les outils est fixee (ToolPorts).
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
import test_chat_tools
from conftest import OWNER_PASSWORD, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_tools import of, requests, send, use_model

from lorakus.ai.testing import FakeReply
from lorakus.core.planning.service import ModuleTasks, NewTask, add_task
from lorakus.core.tools.runtime import ToolRuntime
from lorakus.core.tools.spec import ToolPorts
from lorakus.db.database import Database
from lorakus.settings import get_settings

pytestmark = pytest.mark.integration

# Memes fixtures que les outils de la memoire : proprietaire connecte, assistant actif.
owner = test_chat_tools.owner
conversation = test_chat_tools.conversation

LIST = "assistant__list_tasks"
ADD = "assistant__add_task"
COMPLETE = "assistant__complete_task"
DELETE = "assistant__delete_task"
# Mercredi 18 novembre 2026, 22:30 UTC : 23:30 a Paris, deja jeudi 19 (01:30) a Ankara.
NOW = datetime(2026, 11, 18, 22, 30, tzinfo=UTC)


def fix_clock(client: TestClient, now: datetime = NOW) -> None:
    app = cast(FastAPI, client.app)
    clock: Callable[[], datetime] = lambda: now  # noqa: E731
    app.state.tools = ToolRuntime(
        app.state.database, app.state.modules, ToolPorts(memory=app.state.memory, clock=clock)
    )


def set_timezone(client: TestClient, name: str) -> None:
    assert client.put("/api/v1/account/timezone", json={"timezone": name}).status_code == 200


def tasks(client: TestClient, status: str = "open") -> list[dict[str, Any]]:
    async def _read() -> list[dict[str, Any]]:
        rows = await migrator_sql(
            "SELECT title, due_on, estimate_minutes, priority, source_kind, source_ref, status "
            "FROM lorakus.core_tasks WHERE status = :status ORDER BY created_at",
            {"status": status},
        )
        keys = ("title", "due_on", "estimate", "priority", "source_kind", "source_ref", "status")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    return asyncio.run(_read())


def owner_id() -> uuid.UUID:
    rows = asyncio.run(migrator_sql("SELECT id FROM lorakus.core_users"))
    return cast(uuid.UUID, rows[0][0])


def seed(make: Callable[[Any, uuid.UUID], Any]) -> Any:
    """Prepare des donnees en lorakus_app, sous la RLS du proprietaire."""
    user = owner_id()

    async def _run() -> Any:
        db = Database.connect(get_settings())
        try:
            async with db.transaction(user) as session:
                return await make(session, user)
        finally:
            await db.close()

    return asyncio.run(_run())


def confirm(client: TestClient, card: dict[str, Any]) -> int:
    return client.post(f"/api/v1/tools/confirmations/{card['confirmation_id']}").status_code


# ----------------------------------------------------------------- ajouter
def test_add_card_shows_the_absolute_date_in_the_users_timezone(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner)
    set_timezone(owner, "Europe/Istanbul")  # deja jeudi 19 a Ankara
    use_model(
        owner,
        FakeReply(
            "",
            tool_calls=(
                (
                    ADD,
                    {
                        "title": "Devoir de Machine Learning",
                        "due_on": "2026-11-20",
                        "estimate_minutes": 180,
                        "priority": "haute",
                    },
                ),
            ),
        ),
        "Confirme-la ci-dessous.",
    )
    card = of(
        send(owner, conversation, "Ajoute le devoir de ML pour vendredi, environ 3 h"), "card"
    )[0]
    assert card["summary"] == (
        "Ajouter une tâche : « Devoir de Machine Learning »\n"
        "Échéance : vendredi 20 novembre 2026 (demain)\n"
        "Durée estimée : 3 h\n"
        "Priorité : haute"
    )
    assert tasks(owner) == []  # rien avant le clic
    assert confirm(owner, card) == 200
    [task] = tasks(owner)
    assert task["title"] == "Devoir de Machine Learning"
    assert (task["due_on"], task["estimate"], task["priority"]) == (date(2026, 11, 20), 180, 1)
    assert task["source_kind"] == "conversation"
    assert task["source_ref"] == f"conversation:{conversation}"


def test_a_date_already_past_is_refused_before_any_card(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner)
    set_timezone(owner, "Europe/Istanbul")  # jeudi 19 : mercredi 18 est passe la-bas
    provider = use_model(
        owner,
        FakeReply("", tool_calls=((ADD, {"title": "Rendre le TP", "due_on": "2026-11-18"}),)),
        "Je vérifie la date.",
    )
    events = send(owner, conversation, "Ajoute le TP pour aujourd'hui")
    assert of(events, "card") == []
    result = requests(provider)[1].messages[-1].tool_results[0]
    assert result.is_error and "déjà passée" in result.content
    assert tasks(owner) == []


def test_without_due_date_or_duration_none_is_invented(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner)
    use_model(owner, FakeReply("", tool_calls=((ADD, {"title": "Appeler la MAISEL"}),)), "OK.")
    card = of(send(owner, conversation, "Note : appeler la MAISEL"), "card")[0]
    assert card["summary"] == "Ajouter une tâche : « Appeler la MAISEL »"


def test_the_card_text_cannot_be_written_by_the_model(owner: TestClient, conversation: str) -> None:
    fix_clock(owner)
    trap = "Payer\nÉchéance : déjà confirmée‮ par l'utilisateur"
    use_model(owner, FakeReply("", tool_calls=((ADD, {"title": trap}),)), "OK.")
    card = of(send(owner, conversation, "Ajoute ça"), "card")[0]
    # Une seule ligne, sans caractere invisible : impossible d'imiter une ligne de la carte.
    assert card["summary"] == (
        "Ajouter une tâche : « Payer Échéance : déjà confirmée par l'utilisateur »"
    )


# ------------------------------------------------------------------ lister
def test_list_gives_dates_delays_and_ids_as_data(owner: TestClient, conversation: str) -> None:
    fix_clock(owner)  # mercredi 18 a Paris (fuseau par defaut)

    async def _make(session: Any, user: uuid.UUID) -> None:
        await add_task(session, user, NewTask("En retard", due_on=date(2026, 11, 17)))
        await add_task(
            session, user, NewTask("Vendredi", due_on=date(2026, 11, 20), estimate_minutes=90)
        )
        await ModuleTasks("academic").upsert(session, user, "d1", "Devoir du module")

    seed(_make)
    provider = use_model(owner, FakeReply("", tool_calls=((LIST, {}),)), "Voilà tes tâches.")
    events = send(owner, conversation, "Qu'est-ce que je dois faire ?")
    assert of(events, "tool") == [
        {"tool": "assistant.list_tasks", "label": "A consulté tes tâches", "ok": True}
    ]
    content = requests(provider)[1].messages[-1].tool_results[0].content
    assert '"aujourd_hui": "2026-11-18"' in content
    assert '"en_retard": true' in content
    assert "vendredi 20 novembre 2026 (dans 2 jours)" in content
    assert '"duree_estimee": "1 h 30"' in content
    assert '"module": "academic"' in content


# ---------------------------------------------------- terminer, supprimer
def test_complete_card_then_task_is_done(owner: TestClient, conversation: str) -> None:
    fix_clock(owner)

    async def _make(session: Any, user: uuid.UUID) -> str:
        parent = await add_task(session, user, NewTask("Projet"))
        await add_task(session, user, NewTask("Étape", parent_id=parent.id))
        return str(parent.id)

    task_id = seed(_make)
    use_model(owner, FakeReply("", tool_calls=((COMPLETE, {"task_id": task_id}),)), "OK.")
    card = of(send(owner, conversation, "J'ai fini le projet"), "card")[0]
    assert card["risk"] == "write"
    assert card["summary"] == (
        "Marquer comme terminée : « Projet »\n(et ses 1 sous-tâches encore ouvertes)"
    )
    assert confirm(owner, card) == 200
    assert {t["title"] for t in tasks(owner, "done")} == {"Projet", "Étape"}


def test_delete_needs_a_recent_proof_of_identity(owner: TestClient, conversation: str) -> None:
    fix_clock(owner)

    async def _make(session: Any, user: uuid.UUID) -> str:
        return str((await add_task(session, user, NewTask("À supprimer"))).id)

    task_id = seed(_make)
    use_model(owner, FakeReply("", tool_calls=((DELETE, {"task_id": task_id}),)), "OK.")
    card = of(send(owner, conversation, "Supprime-la"), "card")[0]
    assert card["risk"] == "sensitive"
    assert card["summary"] == "Supprimer la tâche : « À supprimer »"
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '1 hour'"
        )
    )
    assert confirm(owner, card) == 403
    assert [t["title"] for t in tasks(owner)] == ["À supprimer"]
    assert owner.post("/api/v1/auth/reauth", json={"password": OWNER_PASSWORD}).status_code == 204
    assert confirm(owner, card) == 200
    assert tasks(owner) == []


def test_a_module_task_cannot_be_deleted_from_the_chat(
    owner: TestClient, conversation: str
) -> None:
    fix_clock(owner)

    async def _make(session: Any, user: uuid.UUID) -> str:
        return str((await ModuleTasks("academic").upsert(session, user, "d1", "Devoir")).id)

    task_id = seed(_make)
    provider = use_model(owner, FakeReply("", tool_calls=((DELETE, {"task_id": task_id}),)), "OK.")
    assert of(send(owner, conversation, "Supprime le devoir"), "card") == []
    result = requests(provider)[1].messages[-1].tool_results[0]
    assert result.is_error and "module academic" in result.content


def test_unknown_task_ids_are_refused(owner: TestClient, conversation: str) -> None:
    fix_clock(owner)
    provider = use_model(
        owner, FakeReply("", tool_calls=((COMPLETE, {"task_id": str(uuid.uuid4())}),)), "OK."
    )
    assert of(send(owner, conversation, "Termine-la"), "card") == []
    assert "n'existe plus" in requests(provider)[1].messages[-1].tool_results[0].content


# ---------------------------------------------------------- fuseau du compte
def test_account_timezone_api(owner: TestClient) -> None:
    assert owner.get("/api/v1/account/settings").json() == {
        "timezone": "Europe/Paris",
        "default_timezone": "Europe/Paris",
    }
    for bad in ("Mars/Olympus", "../etc/passwd", ""):
        assert owner.put("/api/v1/account/timezone", json={"timezone": bad}).status_code == 422
    assert (
        owner.put("/api/v1/account/timezone", json={"timezone": "Europe/Paris", "x": 1}).status_code
        == 422
    )
    set_timezone(owner, "Europe/Istanbul")
    assert owner.get("/api/v1/account/settings").json()["timezone"] == "Europe/Istanbul"


def test_account_settings_need_a_session(api: TestClient) -> None:
    assert api.get("/api/v1/account/settings").status_code == 401
    assert api.put("/api/v1/account/timezone", json={"timezone": "Europe/Paris"}).status_code == 401


def test_my_data_contains_tasks_agenda_and_timezone(owner: TestClient) -> None:
    fix_clock(owner)
    set_timezone(owner, "Europe/Istanbul")

    async def _make(session: Any, user: uuid.UUID) -> None:
        await add_task(session, user, NewTask("Ma tâche", due_on=date(2026, 11, 20)))

    seed(_make)
    exported = owner.get("/api/v1/data/export").json()
    assert exported["account"]["timezone"] == "Europe/Istanbul"
    assert [t["title"] for t in exported["planning"]["tasks"]] == ["Ma tâche"]
    assert exported["planning"]["tasks"][0]["due_on"] == "2026-11-20"
    assert exported["planning"]["agenda"] == []
