"""Module Assistant par l'API : conversations, reponse en flux, repli, isolation."""

import asyncio
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast

import pytest
from conftest import (
    BASE_URL,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    create_user_sync,
    migrator_sql,
    wipe_identity,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, ProgrammingError

from lorakus.ai.catalog import Catalog
from lorakus.ai.port import ProviderError
from lorakus.ai.router import ModelRouter
from lorakus.ai.testing import DEV_PREFIX, FakeProvider
from lorakus.ai.usage import UsageStore
from lorakus.api.app import create_app
from lorakus.core.identity.passwords import HASHER
from lorakus.db.database import Database
from lorakus.settings import get_settings
from lorakus_modules.assistant.service import FALLBACKS, AssistantService

pytestmark = pytest.mark.integration

OTHER_EMAIL = "autre@example.com"
OTHER_PASSWORD = "un autre mot de passe long"
BASE = "/api/v1/assistant"


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def use_provider(client: TestClient, provider: FakeProvider, budget: str = "3") -> None:
    """Remplace le routeur IA de l'application par un routeur au faux fournisseur."""
    app = _app(client)
    app.state.ai = ModelRouter(
        Catalog.load(),
        {"fake": provider},
        UsageStore(app.state.database),
        monthly_budget_usd=Decimal(budget),
    )


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 204


def enable(client: TestClient, config: dict[str, Any] | None = None) -> None:
    body: dict[str, Any] = {"enabled": True}
    if config is not None:
        body["config"] = config
    assert client.put("/api/v1/modules/assistant", json=body).status_code == 200


def new_conversation(client: TestClient) -> str:
    response = client.post(f"{BASE}/conversations")
    assert response.status_code == 201
    return response.json()["id"]


def send(client: TestClient, conversation_id: str, text: str) -> tuple[str, dict[str, Any]]:
    """Envoie un message et lit le flux SSE : (texte recu, evenement done)."""
    with client.stream(
        "POST", f"{BASE}/conversations/{conversation_id}/messages", json={"content": text}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-store" in response.headers["cache-control"]
        body = "".join(response.iter_text())
    texts: list[str] = []
    done: dict[str, Any] = {}
    for block in body.strip().split("\n\n"):
        name = block.split("\n")[0].removeprefix("event: ")
        data = json.loads(block.split("\n")[1].removeprefix("data: "))
        if name == "delta":
            texts.append(data["text"])
        else:
            done = data
    return "".join(texts), done


@pytest.fixture
def owner() -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    with TestClient(create_app(), base_url=BASE_URL) as client:
        create_user_sync()
        login(client, OWNER_EMAIL, OWNER_PASSWORD)
        yield client


def second_user(app: FastAPI) -> TestClient:
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'user')",
            {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
        )
    )
    other = TestClient(app, base_url=BASE_URL)
    login(other, OTHER_EMAIL, OTHER_PASSWORD)
    enable(other)
    return other


def test_module_is_hidden_until_enabled(owner: TestClient) -> None:
    assert owner.get(f"{BASE}/conversations").status_code == 404
    enable(owner)
    assert owner.get(f"{BASE}/conversations").json() == []


def test_first_conversation_end_to_end(owner: TestClient) -> None:
    enable(owner)
    provider = FakeProvider(replies=["Bonjour Anas, que puis-je faire pour toi ?"])
    use_provider(owner, provider)
    conversation_id = new_conversation(owner)

    text, done = send(owner, conversation_id, "Salut, tu es la ?")

    assert text == "Bonjour Anas, que puis-je faire pour toi ?"
    assert done["status"] == "ok"
    assert done["budget_warning"] is False
    detail = owner.get(f"{BASE}/conversations/{conversation_id}").json()
    assert detail["title"] == "Salut, tu es la ?"
    assert [(m["role"], m["status"]) for m in detail["messages"]] == [
        ("user", "ok"),
        ("assistant", "ok"),
    ]
    assert detail["messages"][1]["id"] == done["message_id"]
    assert detail["messages"][1]["model"] == "echo"
    # Ce qui est parti au modele : le prompt systeme et le seul message de l'utilisateur.
    _, request = provider.calls[0]
    assert request.system.startswith("Tu es Lorakus,")
    assert [(m.role, m.content) for m in request.messages] == [("user", "Salut, tu es la ?")]


def test_following_messages_carry_the_history(owner: TestClient) -> None:
    enable(owner)
    provider = FakeProvider(replies=["Premiere reponse.", "Deuxieme reponse."])
    use_provider(owner, provider)
    conversation_id = new_conversation(owner)

    send(owner, conversation_id, "Premier message")
    send(owner, conversation_id, "Deuxieme message")

    _, request = provider.calls[1]
    assert [(m.role, m.content) for m in request.messages] == [
        ("user", "Premier message"),
        ("assistant", "Premiere reponse."),
        ("user", "Deuxieme message"),
    ]
    # Le titre reste celui du premier message.
    assert owner.get(f"{BASE}/conversations/{conversation_id}").json()["title"] == "Premier message"


def test_display_name_and_timezone_come_from_the_module_configuration(owner: TestClient) -> None:
    enable(owner, {"display_name": "Jarvis", "timezone": "Europe/Istanbul"})
    provider = FakeProvider(replies=["ok"])
    use_provider(owner, provider)

    send(owner, new_conversation(owner), "Qui es-tu ?")

    system = provider.calls[0][1].system
    assert system.startswith("Tu es Jarvis,")
    assert "(Europe/Istanbul)" in system


def test_development_without_key_answers_with_the_fake_echo(owner: TestClient) -> None:
    enable(owner)  # routeur de l'application, tel que construit au demarrage (pas de cle)

    text, done = send(owner, new_conversation(owner), "Test sans cle")

    assert text == DEV_PREFIX + "Test sans cle"
    assert done["status"] == "ok"


def test_budget_reached_gives_the_template_and_keeps_the_message(owner: TestClient) -> None:
    enable(owner)
    provider = FakeProvider(replies=["ne doit pas repondre"])
    use_provider(owner, provider, budget="0")
    conversation_id = new_conversation(owner)

    text, done = send(owner, conversation_id, "Bonjour")

    assert text == FALLBACKS["budget"]
    assert done["status"] == "fallback"
    assert provider.calls == []
    messages = owner.get(f"{BASE}/conversations/{conversation_id}").json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Bonjour"),
        ("assistant", FALLBACKS["budget"]),
    ]


def test_provider_down_gives_the_unavailable_template(owner: TestClient) -> None:
    enable(owner)
    use_provider(owner, FakeProvider(fail_before=ProviderError("unavailable", "panne")))

    text, done = send(owner, new_conversation(owner), "Bonjour")

    assert text == FALLBACKS["unavailable"]
    assert done["status"] == "fallback"


def test_answer_cut_by_the_provider_is_kept_as_interrupted(owner: TestClient) -> None:
    enable(owner)
    use_provider(owner, FakeProvider(replies=["un deux trois quatre"], fail_after_chunks=2))
    conversation_id = new_conversation(owner)

    text, done = send(owner, conversation_id, "Compte")

    assert text == "un deux"
    assert done["status"] == "interrupted"
    saved = owner.get(f"{BASE}/conversations/{conversation_id}").json()["messages"][1]
    assert (saved["content"], saved["status"]) == ("un deux", "interrupted")


@pytest.mark.parametrize("content", ["", "x" * 8001])
def test_message_length_is_validated(owner: TestClient, content: str) -> None:
    enable(owner)
    conversation_id = new_conversation(owner)

    response = owner.post(
        f"{BASE}/conversations/{conversation_id}/messages", json={"content": content}
    )

    assert response.status_code == 422


def test_unknown_conversation_is_404_without_calling_the_model(owner: TestClient) -> None:
    enable(owner)
    provider = FakeProvider(replies=["non"])
    use_provider(owner, provider)

    response = owner.post(
        f"{BASE}/conversations/{uuid.uuid4()}/messages", json={"content": "Bonjour"}
    )

    assert response.status_code == 404
    assert provider.calls == []


def test_conversations_are_listed_newest_first_and_deleted(owner: TestClient) -> None:
    enable(owner)
    use_provider(owner, FakeProvider(replies=["a", "b"]))
    first = new_conversation(owner)
    second = new_conversation(owner)
    send(owner, first, "Je reviens sur la premiere")

    assert [c["id"] for c in owner.get(f"{BASE}/conversations").json()] == [first, second]

    assert owner.delete(f"{BASE}/conversations/{first}").status_code == 204
    assert owner.get(f"{BASE}/conversations/{first}").status_code == 404
    assert owner.delete(f"{BASE}/conversations/{first}").status_code == 404


def test_another_user_cannot_read_write_or_delete_a_conversation(owner: TestClient) -> None:
    enable(owner)
    provider = FakeProvider(replies=["prive"])
    use_provider(owner, provider)
    conversation_id = new_conversation(owner)
    send(owner, conversation_id, "Mon secret")

    other = second_user(_app(owner))

    assert other.get(f"{BASE}/conversations").json() == []
    assert other.get(f"{BASE}/conversations/{conversation_id}").status_code == 404
    response = other.post(
        f"{BASE}/conversations/{conversation_id}/messages", json={"content": "Je lis ?"}
    )
    assert response.status_code == 404
    assert other.delete(f"{BASE}/conversations/{conversation_id}").status_code == 404
    assert len(provider.calls) == 1
    assert len(owner.get(f"{BASE}/conversations/{conversation_id}").json()["messages"]) == 2


@pytest.mark.anyio
async def test_database_refuses_a_message_attached_to_another_users_conversation() -> None:
    await wipe_identity()
    database = Database.connect(get_settings())
    first, second = uuid.uuid4(), uuid.uuid4()
    for user_id, email in ((first, "a@example.com"), (second, "b@example.com")):
        await migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, 'x', 'user')",
            {"id": user_id, "email": email},
        )
    try:
        service = AssistantService(database, cast(ModelRouter, None))
        conversation = await service.create_conversation(first)
        # Le second utilisateur connait l'identifiant et tente d'y attacher un message a lui.
        with pytest.raises((IntegrityError, ProgrammingError)):
            async with database.transaction(second) as session:
                from sqlalchemy import text

                await session.execute(
                    text(
                        "INSERT INTO lorakus.asst_messages (id, user_id, conversation_id, role, "
                        "content, status) VALUES (:id, :user, :conv, 'user', 'intrus', 'ok')"
                    ),
                    {"id": uuid.uuid4(), "user": second, "conv": conversation.id},
                )
    finally:
        await database.close()
    rows = await migrator_sql("SELECT count(*) FROM lorakus.asst_messages")
    assert rows == [(0,)]


@pytest.mark.anyio
async def test_client_leaving_mid_answer_keeps_the_partial_reply() -> None:
    await wipe_identity()
    database = Database.connect(get_settings())
    user_id = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'a@example.com', 'x', 'user')",
        {"id": user_id},
    )
    try:
        router = ModelRouter(
            Catalog.load(),
            {"fake": FakeProvider(replies=["un deux trois quatre"])},
            UsageStore(database),
            monthly_budget_usd=Decimal(3),
        )
        service = AssistantService(database, router)
        conversation = await service.create_conversation(user_id)
        from lorakus_modules.assistant.config import AssistantConfig

        turn = await service.start_turn(user_id, conversation.id, "Compte", AssistantConfig())
        reply = service.play(turn)
        await anext(reply)
        await anext(reply)
        await reply.aclose()  # le telephone se verrouille : la connexion se ferme

        _, messages = await service.conversation(user_id, conversation.id)
    finally:
        await database.close()
    assert [(m.role, m.content, m.status) for m in messages] == [
        ("user", "Compte", "ok"),
        ("assistant", "un deux", "interrupted"),
    ]
