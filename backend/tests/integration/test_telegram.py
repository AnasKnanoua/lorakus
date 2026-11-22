"""Bot Telegram (P5, PR 54, scenario 5) de bout en bout : liaison par code, capture d'idees,
refus, second canal des rappels sans detail, isolation, corpus d'attaques.

Sur PostgreSQL, en lorakus_app (RLS), avec le vrai traitement des messages ; Telegram est
remplace par FakeBot (messages a relever, reponses notees).
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import BASE_URL, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD
from test_signals import (
    BASE as NOTIFICATIONS,
)
from test_signals import (
    THURSDAY,
    TUESDAY,
    at,
    owner,
    run,
    sergent,
    task,
    watch,
    work,
)

from lorakus.api.routes import notifications as notifications_route
from lorakus.api.routes import telegram as telegram_route
from lorakus.core.identity.passwords import HASHER
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.signals.dispatch import TelegramChannel, dispatch_due
from lorakus.core.telegram import inbox
from lorakus.core.telegram.bot import Update
from lorakus.core.telegram.inbox import PollState, poll_round
from lorakus.core.tools.spec import ToolCall
from lorakus.settings import get_settings
from lorakus_modules.projects.tools import NoArgs, _list  # pyright: ignore[reportPrivateUsage]

pytestmark = pytest.mark.integration
__all__ = ["owner", "sergent"]

BASE = "/api/v1/telegram"
CHAT = 424242
OTHER_CHAT = 515151
CORPUS: list[dict[str, str]] = json.loads(
    (Path(__file__).parents[1] / "security" / "injection_corpus.json").read_text()
)["attacks"]


class FakeBot:
    """Telegram : des messages a relever (une fois chacun), et ce que le bot a envoye."""

    def __init__(self) -> None:
        self.pending: list[Update] = []
        self.sent: list[tuple[int, str]] = []
        self.next_id = 1

    def receive(
        self, text: str | None, chat: int = CHAT, private: bool = True, bot: bool = False
    ) -> None:
        self.pending.append(Update(self.next_id, chat, private, bot, text))
        self.next_id += 1

    async def updates(self, offset: int | None, wait_s: int) -> list[Update]:
        ready = [u for u in self.pending if offset is None or u.update_id >= offset]
        self.pending = []
        return ready

    async def send(self, chat_id: int, message: str) -> None:
        self.sent.append((chat_id, message))


@pytest.fixture
def available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORAKUS_TELEGRAM_AVAILABLE", "true")
    get_settings.cache_clear()


@pytest.fixture
def projects(owner: TestClient) -> TestClient:
    assert owner.put("/api/v1/modules/projects", json={"enabled": True}).status_code == 200
    return owner


def fix_now(client: TestClient, now: datetime) -> None:
    cast(FastAPI, client.app).dependency_overrides[telegram_route.get_now] = lambda: now


def poll(bot: FakeBot, state: PollState, now: datetime) -> dict[str, int]:
    """Un releve ; le temps du releve est simule : deux tours, le second vide."""
    ticks = iter([0.0, 0.0, 30.0, 60.0])
    return run(
        lambda db: poll_round(
            db,
            bot,
            ModuleRegistry.from_entry_points(),
            state,
            lambda: now,
            clock=lambda: next(ticks),
        )
    )


def say(
    bot: FakeBot, state: PollState, text: str | None, now: datetime, chat: int = CHAT
) -> str | None:
    """Envoie un message au bot ; rend sa reponse (ou None s'il n'a rien repondu)."""
    before = len(bot.sent)
    bot.receive(text, chat)
    poll(bot, state, now)
    replies = bot.sent[before:]
    assert len(replies) <= 1
    return replies[0][1] if replies else None


def link(
    client: TestClient, bot: FakeBot, state: PollState, now: datetime, chat: int = CHAT
) -> str:
    fix_now(client, now)
    response = client.post(f"{BASE}/code")
    assert response.status_code == 201, response.text
    code = response.json()["code"]
    reply = say(bot, state, f"/start {code}", now, chat)
    assert reply is not None and reply.startswith("C'est fait")
    return cast(str, code)


def ideas() -> list[tuple[Any, ...]]:
    return asyncio.run(
        migrator_sql(
            "SELECT text, source_kind, source_ref FROM lorakus.proj_ideas ORDER BY created_at"
        )
    )


NOW = datetime(2026, 11, 23, 9, tzinfo=UTC)


# ------------------------------------------------------------------ scenario 5
def test_scenario_5_an_idea_sent_to_the_bot_lands_in_the_idea_box(
    projects: TestClient, available: None
) -> None:
    bot, state = FakeBot(), PollState()
    assert projects.get(BASE).json() == {
        "available": True,
        "linked": False,
        "notify": False,
        "linked_at": None,
        "last_message_at": None,
    }
    fix_now(projects, NOW)
    created = projects.post(f"{BASE}/code").json()
    assert len(created["code"]) == 9 and created["code"][4] == "-"
    assert datetime.fromisoformat(created["expires_at"]) == NOW + timedelta(minutes=10)

    assert say(bot, state, f"/start {created['code']}", NOW) == inbox.LINKED
    reply = say(bot, state, "Créer un club d'échecs à TSP", NOW + timedelta(minutes=1))
    assert reply == "Idée notée dans ta boîte : « Créer un club d'échecs à TSP »"
    assert ideas() == [("Créer un club d'échecs à TSP", "telegram", None)]
    assert [i["text"] for i in projects.get("/api/v1/projects/ideas").json()] == [
        "Créer un club d'échecs à TSP"
    ]
    status = projects.get(BASE).json()
    assert status["linked"]
    assert datetime.fromisoformat(status["last_message_at"]) == NOW + timedelta(minutes=1)

    # Une seconde fois : refus lisible, pas de doublon.
    assert (
        say(bot, state, "créer un club d'échecs à TSP", NOW) == "Cette idée est déjà dans ta boîte."
    )
    # Plusieurs lignes : rangees en une seule.
    say(bot, state, "Ligne une\nligne deux", NOW)
    assert ideas()[-1][0] == "Ligne une ligne deux"
    assert say(bot, state, "x" * 501, NOW) == "Idée trop longue (500 caractères au plus)."
    assert len(ideas()) == 2


def test_help_commands_and_other_messages(projects: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(projects, bot, state, NOW)
    assert say(bot, state, "/aide", NOW) == inbox.HELP
    assert say(bot, state, "/start", NOW) == inbox.HELP
    assert say(bot, state, "/supprimer_tout", NOW) == inbox.UNKNOWN_COMMAND
    assert say(bot, state, None, NOW) == inbox.TEXT_ONLY  # une photo, un autocollant
    assert ideas() == []


def test_an_unlinked_chat_gets_one_explanation_and_nothing_is_stored(
    projects: TestClient, available: None
) -> None:
    bot, state = FakeBot(), PollState()
    assert say(bot, state, "Une idée", NOW) == inbox.NOT_LINKED
    assert say(bot, state, "/aide", NOW) == inbox.NOT_LINKED
    # Groupes et autres bots : ignores, sans reponse.
    bot.receive("Une idée de groupe", chat=-100, private=False)
    bot.receive("Je suis un bot", bot=True)
    poll(bot, state, NOW)
    assert len(bot.sent) == 2
    assert ideas() == []


def test_a_code_works_once_for_ten_minutes(projects: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    fix_now(projects, NOW)
    old = projects.post(f"{BASE}/code").json()["code"]
    fresh = projects.post(f"{BASE}/code").json()["code"]  # remplace le precedent
    assert say(bot, state, old, NOW) == inbox.BAD_CODE
    assert say(bot, state, fresh, NOW + timedelta(minutes=10, seconds=1)) == inbox.BAD_CODE
    late = link(projects, bot, state, NOW + timedelta(minutes=20))
    assert (
        say(bot, state, f"/start {late}", NOW + timedelta(minutes=21), OTHER_CHAT) == inbox.BAD_CODE
    )
    assert asyncio.run(migrator_sql("SELECT count(*) FROM lorakus.core_telegram_codes")) == [(0,)]


def test_guessing_codes_stops_after_five_tries(projects: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    for n in range(inbox.MAX_CODE_ATTEMPTS):
        assert say(bot, state, f"AAAA-AAA{n + 2}", NOW) == inbox.BAD_CODE
    fix_now(projects, NOW)
    good = projects.post(f"{BASE}/code").json()["code"]
    assert say(bot, state, good, NOW) is None  # plus de reponse, plus d'essai
    assert projects.get(BASE).json()["linked"] is False
    assert say(bot, state, good, NOW, OTHER_CHAT) == inbox.LINKED  # une autre discussion


def test_a_chat_serves_one_account(projects: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(projects, bot, state, NOW)
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'user')",
            {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
        )
    )
    other = TestClient(cast(FastAPI, projects.app), base_url=BASE_URL)
    login = {"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    assert other.post("/api/v1/auth/login", json=login).status_code == 204
    assert other.get(BASE).json()["linked"] is False  # rien de l'autre compte
    assert other.delete(BASE).status_code == 404
    link(other, bot, state, NOW)  # la meme discussion passe a l'autre compte
    assert projects.get(BASE).json()["linked"] is False
    assert other.get(BASE).json()["linked"] is True


def test_unlinking_from_the_app(projects: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(projects, bot, state, NOW)
    pending = projects.post(f"{BASE}/code").json()["code"]  # un code demande, jamais envoye
    assert projects.delete(BASE).status_code == 204
    assert say(bot, state, "Une idée", NOW) == inbox.NOT_LINKED
    assert say(bot, state, pending, NOW) == inbox.BAD_CODE  # delier oublie aussi le code
    assert projects.delete(BASE).status_code == 404


def test_without_the_idea_box_nothing_is_noted(owner: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(owner, bot, state, NOW)  # projects jamais active
    assert say(bot, state, "Une idée", NOW) == inbox.NO_BOX
    assert ideas() == []


def test_without_a_bot_no_code_is_given(owner: TestClient) -> None:
    assert owner.get(BASE).json()["available"] is False
    assert owner.post(f"{BASE}/code").status_code == 409


# ------------------------------------------------------- second canal des rappels
def channel(bot: FakeBot) -> TelegramChannel:
    return TelegramChannel(bot, "https://app.lorakus.app")


def test_reminders_also_arrive_on_telegram_without_any_detail(
    owner: TestClient, available: None
) -> None:
    bot, state = FakeBot(), PollState()
    link(owner, bot, state, at(7))
    assert owner.put(BASE, json={"notify": True}).json()["notify"] is True
    task("CSEC507 : rapport secret", THURSDAY, 60)
    watch(at(8))
    run(lambda db: dispatch_due(db, None, at(8, 1), telegram=channel(bot)))
    work(TUESDAY)
    sent_before = len(bot.sent)
    # Aucun appareil Web Push (pas de cles) : Telegram suffit pour le niveau 2.
    run(lambda db: dispatch_due(db, None, at(10, 0, TUESDAY), telegram=channel(bot)))
    [(chat, message)] = bot.sent[sent_before:]
    assert chat == CHAT
    assert (
        message == "Lorakus : un rappel t'attend. Ouvre Ma journée : https://app.lorakus.app/today"
    )
    assert "CSEC507" not in message and "secret" not in message
    delivered = asyncio.run(
        migrator_sql("SELECT delivered, failed FROM lorakus.core_interventions WHERE level = 2")
    )
    assert delivered == [(1, 0)]


def test_telegram_stays_silent_unless_chosen(owner: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(owner, bot, state, at(7))
    task("Rapport", THURSDAY, 60)
    watch(at(8))
    run(lambda db: dispatch_due(db, None, at(8, 1), telegram=channel(bot)))
    work(TUESDAY)
    sent = len(bot.sent)
    run(lambda db: dispatch_due(db, None, at(10, 0, TUESDAY), telegram=channel(bot)))
    assert len(bot.sent) == sent  # notify : faux par defaut
    assert owner.put(BASE, json={"notify": False}).status_code == 200


def test_the_test_notification_reaches_telegram_too(owner: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(owner, bot, state, at(3))
    app = cast(FastAPI, owner.app)
    app.dependency_overrides[notifications_route.get_now] = lambda: at(3)
    assert owner.post(f"{NOTIFICATIONS}/push/test").status_code == 409  # Telegram non choisi
    owner.put(BASE, json={"notify": True})
    assert owner.post(f"{NOTIFICATIONS}/push/test").status_code == 202
    sent = len(bot.sent)
    run(lambda db: dispatch_due(db, None, at(3, 1), telegram=channel(bot)))
    assert bot.sent[sent:] == [
        (CHAT, "Lorakus : notification de test. Les rappels arriveront aussi ici, sans détail.")
    ]


# ------------------------------------------------------------- export, attaques
def test_my_data_lists_the_telegram_link(owner: TestClient, available: None) -> None:
    bot, state = FakeBot(), PollState()
    link(owner, bot, state, NOW)
    [entry] = owner.get("/api/v1/data/export").json()["notifications"]["telegram"]
    assert entry["chat_id"] == CHAT and entry["notify"] is False


@pytest.mark.parametrize("attack", CORPUS, ids=[a["id"] for a in CORPUS])
def test_an_attack_sent_to_the_bot_is_only_ever_an_inert_idea(
    projects: TestClient, available: None, attack: dict[str, str]
) -> None:
    bot, state = FakeBot(), PollState()
    link(projects, bot, state, NOW)

    counts = (
        "SELECT count(*) FROM lorakus.core_tasks",
        "SELECT count(*) FROM lorakus.core_memory_facts",
        "SELECT count(*) FROM lorakus.core_signals",
        "SELECT count(*) FROM lorakus.proj_projects",
        "SELECT count(*) FROM lorakus.core_tool_confirmations",
        "SELECT count(*) FROM lorakus.core_telegram_links",
    )

    def others() -> list[Any]:
        return [asyncio.run(migrator_sql(query)) for query in counts]

    before = others()
    reply = say(bot, state, attack["payload"], NOW)
    assert reply is not None
    assert (
        reply.startswith("Idée notée dans ta boîte")
        or reply in ("Écris ton idée.", "Idée trop longue (500 caractères au plus).")
        or reply.startswith(("Commande inconnue", "Envoie-moi une idée"))
    )
    assert others() == before  # rien d'autre ne bouge : ni tache, ni souvenir, ni lien
    stored = ideas()
    assert all(kind == "telegram" and "\n" not in text for text, kind, _ in stored)

    async def read(db: Any) -> dict[str, Any]:
        [(raw,)] = await migrator_sql("SELECT user_id FROM lorakus.core_telegram_links")
        user = cast(uuid.UUID, raw)
        async with db.transaction(user) as session:
            return await _list(ToolCall(user, session), NoArgs())

    shown = run(read)["dernieres_idees"]
    assert len(shown) == len(stored)
    for line in shown:
        assert "<" not in line and ">" not in line  # inert() : rien qui ferme un bloc
