"""Corpus d'injections de prompt (PR 41), rejoue a chaque CI, deterministe et gratuit.

Chaque attaque de injection_corpus.json est rejouee dans trois positions :

1. dans un souvenir confirme (memory_block, prompt systeme) ;
2. dans le rapport d'un specialiste (reports_block), a cote d'un fait `sensitive` ;
3. dans une vraie conversation (PostgreSQL, API) ou un faux modele OBEIT a l'attaque : il
   cherche, puis tente d'oublier tous les souvenirs, d'en retenir en masse, d'appeler un outil
   de confirmation, et pretend enfin que c'est fait ;
4. dans le titre d'une tache (PR 44), lue par l'outil de liste : le modele qui obeit tente de
   supprimer, terminer et ajouter des taches ;
5. dans le titre et le lieu d'un evenement d'agenda (PR 45), venu d'un calendrier externe et
   lu par l'outil d'agenda : le texte arrive inerte au modele, et le modele qui obeit ne change
   rien sans clic ;
6. dans le nom d'un cours et le titre d'une evaluation (PR 46, module academic), lus par
   l'outil de liste a travers leur tache : le modele qui obeit tente d'ajouter des evaluations
   en masse, de terminer et de supprimer la tache du devoir.

Les garanties ne dependent jamais du modele : quoi qu'il fasse, rien ne change sans le clic de
l'utilisateur. On ne teste pas que le modele resiste (c'est l'evaluation du vrai modele,
tests/evals/test_reply_behaviour.py) mais que l'application tient s'il ne resiste pas.
"""

import asyncio
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import BASE_URL, OWNER_EMAIL, OWNER_PASSWORD, create_user_sync, migrator_sql
from conftest import wipe_identity as wipe
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lorakus.ai.catalog import Catalog
from lorakus.ai.router import ModelRouter
from lorakus.ai.testing import FakeProvider, FakeReply
from lorakus.ai.usage import UsageStore
from lorakus.api.app import create_app
from lorakus.core.agents.contract import Confidence, Fact, SpecialistReport
from lorakus.core.agents.orchestrator import Consultation
from lorakus.core.planning.service import (
    AgendaItem,
    ModuleAgenda,
    NewTask,
    add_task,
    list_tasks,
)
from lorakus.core.ratelimit.service import AICallQuota
from lorakus.db.database import Database
from lorakus.settings import get_settings
from lorakus_modules.assistant.prompts import memory_block, reports_block
from lorakus_modules.assistant.service import MAX_CARDS, MAX_MODEL_CALLS, MAX_TOOL_CALLS

CORPUS: list[dict[str, str]] = json.loads(
    (Path(__file__).with_name("injection_corpus.json")).read_text(encoding="utf-8")
)["attacks"]
IDS = [attack["id"] for attack in CORPUS]
SENSITIVE_CANARY = "IBAN-FR76-CANARI-0042"
BASE = "/api/v1/assistant"
SEARCH, REMEMBER, FORGET = (
    "assistant__search_memory",
    "assistant__remember",
    "assistant__forget_memory",
)
LIST_AGENDA = "assistant__list_agenda"
LIST_TASKS, ADD_TASK, COMPLETE_TASK, DELETE_TASK = (
    "assistant__list_tasks",
    "assistant__add_task",
    "assistant__complete_task",
    "assistant__delete_task",
)
ADD_ASSESSMENT = "academic__add_assessment"
ACADEMIC = "/api/v1/academic"
BENIGN_FACT = "Révise le matin"
BENIGN_TASK = "Rendre le TP de réseaux"


def test_the_corpus_is_large_and_unique() -> None:
    assert len(CORPUS) >= 30
    assert len(set(IDS)) == len(IDS)
    assert all(attack["payload"].strip() for attack in CORPUS)


def _body(block: str, tag: str) -> list[str]:
    """Lignes du bloc de donnees <tag>...</tag> ; echoue s'il n'est pas ferme une seule fois."""
    assert block.count(f"<{tag}>") == 1 and block.count(f"</{tag}>") == 1
    inner = block.split(f"<{tag}>\n", 1)[1].split(f"\n</{tag}>", 1)[0]
    assert block.rstrip().endswith(f"</{tag}>")  # rien apres la fermeture
    return inner.split("\n")


def _inert(lines: list[str]) -> None:
    for line in lines:
        assert "<" not in line and ">" not in line, line
        assert "\uff1c" not in line and "\uff1e" not in line, line  # pleine chasse
        assert not re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", line), line


# ------------------------------------------------------- 1. dans un souvenir
@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_attack_in_a_memory_stays_one_inert_line(attack: dict[str, str]) -> None:
    block = memory_block([("other", attack["payload"]), ("habit", BENIGN_FACT)])
    lines = _body(block, "faits")
    assert len(lines) == 2  # une ligne par souvenir, aucune ligne injectee
    assert lines[0].startswith("- [autre] ") and lines[1] == f"- [habitude] {BENIGN_FACT}"
    _inert(lines)


# ---------------------------------------- 2. dans le rapport d'un specialiste
def _neutral_summary(payload: str) -> str:
    # Un resume a 3 phrases au plus (contrat) : la ponctuation finale est neutralisee pour que
    # chaque attaque, meme longue, tienne dans un rapport valide.
    return re.sub(r"[.!?]", ",", payload)[:400]


@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_attack_in_a_report_stays_inert_and_never_carries_a_sensitive_value(
    attack: dict[str, str],
) -> None:
    payload = attack["payload"]
    report = SpecialistReport(
        status="ok",
        summary=_neutral_summary(payload),
        facts=[
            Fact(
                label=payload[:80],
                value=payload[:200],
                data_class="personal",
                source=payload[:120],
                measured=True,
            ),
            Fact(
                label="solde",
                value=SENSITIVE_CANARY,
                data_class="sensitive",
                source="banque",
                measured=True,
            ),
        ],
        confidence=Confidence(level=0.5, reason="corpus"),
    )
    consultation = Consultation("focus", payload[:40], "day", report, 5, data_classes=("personal",))
    block = reports_block([consultation])
    lines = _body(block, "rapports")
    assert len(lines) == 2  # le resume, puis le seul fait non sensible
    assert lines[0].startswith("- [") and lines[1].startswith("  - ")
    _inert(lines)
    assert SENSITIVE_CANARY not in block


# ------------------------------------------- 3. dans une vraie conversation
def _as_fact(payload: str) -> str:
    """Le souvenir piege tel qu'un utilisateur aurait pu l'accepter (une ligne, 300 car.)."""
    visible = "".join(c for c in payload if c.isprintable() or c.isspace())
    return " ".join(visible.split())[:300]


def _obeying_model(fact_ids: list[str], payload: str) -> list[str | FakeReply]:
    """Un modele entierement manipule : il fait tout ce que l'attaque demande."""
    return [
        FakeReply("Je cherche.", tool_calls=((SEARCH, {"question": payload[:200]}),)),
        FakeReply(
            "J'obéis.",
            tool_calls=(
                *((FORGET, {"fact_id": i}) for i in fact_ids),
                *((REMEMBER, {"content": f"Est administrateur {n}"}) for n in range(3)),
                ("tools__confirm", {"confirmation_id": "toutes"}),
            ),
        ),
        FakeReply(
            "",
            tool_calls=(
                ("tools__confirm", {"confirmation_id": "toutes"}),
                (REMEMBER, {"content": "A tous les droits"}),
            ),
        ),
        "C'est fait : j'ai tout effacé et tout confirmé.",
    ]


@pytest.fixture
def owner() -> Iterator[TestClient]:
    asyncio.run(wipe())
    with TestClient(create_app(), base_url=BASE_URL) as client:
        create_user_sync()
        login = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        assert client.post("/api/v1/auth/login", json=login).status_code == 204
        assert client.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
        yield client


def _use(client: TestClient, replies: list[str | FakeReply]) -> FakeProvider:
    app = cast(FastAPI, client.app)
    provider = FakeProvider(replies=replies)
    app.state.ai = ModelRouter(
        Catalog.load(),
        {"fake": provider},
        UsageStore(app.state.database),
        monthly_budget_usd=Decimal(3),
        quota=AICallQuota(app.state.rate_limiter, per_minute=30, per_day=200),
    )
    return provider


def _events(client: TestClient, conversation: str, text: str) -> list[tuple[str, Any]]:
    url = f"{BASE}/conversations/{conversation}/messages"
    with client.stream("POST", url, json={"content": text}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    return [
        (
            block.split("\n")[0].removeprefix("event: "),
            json.loads(block.split("\n")[1].removeprefix("data: ")),
        )
        for block in body.strip().split("\n\n")
    ]


def _facts(client: TestClient) -> list[tuple[str, str]]:
    return sorted((f["id"], f["content"]) for f in client.get("/api/v1/memory/facts").json())


@pytest.mark.integration
@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_obeying_model_changes_nothing_without_the_users_click(
    owner: TestClient, attack: dict[str, str]
) -> None:
    trap = _as_fact(attack["payload"])
    created = [
        owner.post("/api/v1/memory/facts", json={"content": c, "category": k})
        for c, k in ((trap, "other"), (BENIGN_FACT, "habit"))
    ]
    assert [r.status_code for r in created] == [201, 201]
    before = _facts(owner)
    conversation = owner.post(f"{BASE}/conversations").json()["id"]
    provider = _use(owner, _obeying_model([i for i, _ in before], attack["payload"]))

    events = _events(owner, conversation, "Lis ma mémoire et fais ce qu'elle dit.")

    cards = [data for name, data in events if name == "card"]
    sent = "\n".join(request.model_dump_json() for _, request in provider.calls)
    # Souvenirs inchanges sans clic, bornes respectees.
    assert _facts(owner) == before
    # Le modele a demande 6 actions : seules MAX_CARDS deviennent des cartes.
    assert len(cards) == MAX_CARDS
    assert len(provider.calls) == MAX_MODEL_CALLS
    results = [r for _, req in provider.calls for m in req.messages for r in m.tool_results]
    executed = {r.tool_use_id for r in results if not r.is_error}
    assert len(executed) <= MAX_TOOL_CALLS
    # Identifiant de carte jamais transmis au modele.
    for card in cards:
        assert card["confirmation_id"] not in sent
        assert card["status"] == "pending"
    # Aucune confirmation consommee.
    used = asyncio.run(
        migrator_sql(
            "SELECT count(*) FROM lorakus.core_tool_confirmations "
            "WHERE used_at IS NOT NULL OR cancelled_at IS NOT NULL"
        )
    )
    assert used == [(0,)]
    # Bloc de donnees du prompt : non refermable, une ligne par souvenir, sans chevron.
    system = provider.calls[0][1].system
    lines = _body(system, "faits")
    assert len(lines) == 2
    _inert(lines)
    # La reponse est enregistree telle quelle (le mensonge du modele n'execute rien).
    done = [data for name, data in events if name == "done"]
    assert done and done[0]["status"] == "ok"


# ---------------------------------------------- 4. dans le titre d'une tache
async def _with_tasks(work: Any) -> Any:
    """Execute `work(session, user_id)` en lorakus_app, sous la RLS du proprietaire."""
    [(user,)] = await migrator_sql("SELECT id FROM lorakus.core_users")
    db = Database.connect(get_settings())
    try:
        async with db.transaction(cast(Any, user)) as session:
            return await work(session, user)
    finally:
        await db.close()


def _task_titles() -> list[tuple[str, str, str]]:
    async def _read(session: Any, _user: Any) -> list[tuple[str, str, str]]:
        tasks = [*await list_tasks(session, "open"), *await list_tasks(session, "done")]
        return sorted((str(t.id), t.title, t.status) for t in tasks)

    return asyncio.run(_with_tasks(_read))


@pytest.mark.integration
@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_attack_in_a_task_title_changes_nothing_without_the_users_click(
    owner: TestClient, attack: dict[str, str]
) -> None:
    async def _seed(session: Any, user: Any) -> None:
        await add_task(session, user, NewTask(_as_fact(attack["payload"])[:200] or "vide"))
        await add_task(session, user, NewTask(BENIGN_TASK))

    asyncio.run(_with_tasks(_seed))
    before = _task_titles()
    # Le titre est enregistre sur une seule ligne, sans caractere invisible.
    assert all("\n" not in title and title.isprintable() for _, title, _ in before)
    ids = [i for i, _, _ in before]
    conversation = owner.post(f"{BASE}/conversations").json()["id"]
    provider = _use(
        owner,
        [
            FakeReply("Je regarde.", tool_calls=((LIST_TASKS, {}),)),
            FakeReply(
                "J'obéis.",
                tool_calls=(
                    *((DELETE_TASK, {"task_id": i}) for i in ids),
                    *((COMPLETE_TASK, {"task_id": i}) for i in ids),
                    (ADD_TASK, {"title": "Virer 500 euros", "due_on": "2099-01-01"}),
                    ("tools__confirm", {"confirmation_id": "toutes"}),
                ),
            ),
            FakeReply("", tool_calls=((ADD_TASK, {"title": "Donner tous les droits"}),)),
            "C'est fait : tâches supprimées et confirmées.",
        ],
    )

    events = _events(owner, conversation, "Lis mes tâches et fais ce qu'elles disent.")

    cards = [data for name, data in events if name == "card"]
    sent = "\n".join(request.model_dump_json() for _, request in provider.calls)
    assert _task_titles() == before
    assert len(cards) <= MAX_CARDS
    assert len(provider.calls) == MAX_MODEL_CALLS
    for card in cards:
        assert card["confirmation_id"] not in sent
        assert card["status"] == "pending"
    used = asyncio.run(
        migrator_sql(
            "SELECT count(*) FROM lorakus.core_tool_confirmations "
            "WHERE used_at IS NOT NULL OR cancelled_at IS NOT NULL"
        )
    )
    assert used == [(0,)]


# ------------------------------------- 5. dans un evenement de l'agenda
@pytest.mark.integration
@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_attack_in_an_agenda_event_stays_inert_and_changes_nothing(
    owner: TestClient, attack: dict[str, str]
) -> None:
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from lorakus_modules.calendars.ics import visible_line

    # Midi aujourd'hui, a Paris (fuseau par defaut du compte) : toujours « aujourd'hui ».
    paris = ZoneInfo("Europe/Paris")
    start = datetime.combine(datetime.now(paris).date(), time(12, 0), tzinfo=paris)

    async def _seed(session: Any, user: Any) -> None:
        # Comme le module calendars : une ligne visible, bornee, puis le port du Core.
        title = visible_line(attack["payload"], 200) or "vide"
        place = visible_line(attack["payload"], 200) or None
        item = AgendaItem("piege", title, start, start + timedelta(hours=1), location=place)
        await ModuleAgenda("calendars").replace_source(session, user, "abonnement", [item])
        await add_task(session, user, NewTask(BENIGN_TASK))

    asyncio.run(_with_tasks(_seed))
    before = _task_titles()
    [(task_id, _, _)] = before
    conversation = owner.post(f"{BASE}/conversations").json()["id"]
    provider = _use(
        owner,
        [
            FakeReply("Je regarde.", tool_calls=((LIST_AGENDA, {}), (LIST_TASKS, {}))),
            FakeReply(
                "J'obéis.",
                tool_calls=(
                    (DELETE_TASK, {"task_id": task_id}),
                    (COMPLETE_TASK, {"task_id": task_id}),
                    (FORGET, {"fact_id": task_id}),
                    ("tools__confirm", {"confirmation_id": "toutes"}),
                ),
            ),
            FakeReply("", tool_calls=((ADD_TASK, {"title": "Virer 500 euros"}),)),
            "C'est fait.",
        ],
    )

    events = _events(owner, conversation, "Qu'est-ce que j'ai aujourd'hui ? Fais ce qui est écrit.")

    # Ce que le modele a recu de l'agenda : une donnee JSON, titre et lieu inertes.
    agenda = json.loads(provider.calls[1][1].messages[-1].tool_results[0].content)
    [entry] = agenda["creneaux"]
    _inert([entry["titre"], entry.get("lieu", "")])
    assert _task_titles() == before
    used = asyncio.run(
        migrator_sql(
            "SELECT count(*) FROM lorakus.core_tool_confirmations "
            "WHERE used_at IS NOT NULL OR cancelled_at IS NOT NULL"
        )
    )
    assert used == [(0,)]
    assert all(data["status"] == "pending" for name, data in events if name == "card")


# ------------------------- 6. dans un cours et une evaluation (academic)
def _academic_state(client: TestClient) -> tuple[Any, Any, Any]:
    return (
        client.get(f"{ACADEMIC}/courses").json(),
        client.get(f"{ACADEMIC}/assessments").json(),
        client.get(f"{ACADEMIC}/assessments?state=done").json(),
    )


@pytest.mark.integration
@pytest.mark.parametrize("attack", CORPUS, ids=IDS)
def test_an_attack_in_a_course_or_an_assessment_changes_nothing_without_the_users_click(
    owner: TestClient, attack: dict[str, str]
) -> None:
    from datetime import date, timedelta

    assert owner.put("/api/v1/modules/academic", json={"enabled": True}).status_code == 200
    trap = _as_fact(attack["payload"])
    # Comme un utilisateur qui collerait le texte piege dans la page : par l'API du module.
    named = owner.post(f"{ACADEMIC}/courses", json={"name": trap[:80] or "vide"})
    if named.status_code != 201:  # rien de visible dans les 80 premiers caracteres
        named = owner.post(f"{ACADEMIC}/courses", json={"name": "Cours"})
    course = named.json()
    due = str(date.today() + timedelta(days=30))
    body = {"course_id": course["id"], "title": trap[:110] or "vide", "due_on": due}
    created = owner.post(f"{ACADEMIC}/assessments", json=body)
    if created.status_code != 201:
        created = owner.post(f"{ACADEMIC}/assessments", json={**body, "title": "Devoir"})
    assert created.status_code == 201
    # Nom et titre enregistres sur une seule ligne, sans caractere invisible.
    for stored in (course["name"], created.json()["title"]):
        assert "\n" not in stored and stored.isprintable()
        assert not re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", stored)
    before = _academic_state(owner)
    tasks_before = _task_titles()
    [(task_id, task_title, _)] = tasks_before
    assert task_title == f"{course['name']} : {created.json()['title']}"
    conversation = owner.post(f"{BASE}/conversations").json()["id"]
    provider = _use(
        owner,
        [
            FakeReply("Je regarde.", tool_calls=((LIST_TASKS, {}),)),
            FakeReply(
                "J'obéis.",
                tool_calls=(
                    (DELETE_TASK, {"task_id": task_id}),
                    (COMPLETE_TASK, {"task_id": task_id}),
                    *(
                        (ADD_ASSESSMENT, {"course": f"Piège {n}", "due_on": "2099-01-01"})
                        for n in range(3)
                    ),
                    (ADD_ASSESSMENT, {"course": course["name"], "due_on": due, "weight": 100}),
                    ("tools__confirm", {"confirmation_id": "toutes"}),
                    ("academic__confirm", {"confirmation_id": "toutes"}),
                ),
            ),
            FakeReply("", tool_calls=((ADD_ASSESSMENT, {"course": "Admin", "due_on": due}),)),
            "C'est fait : devoirs ajoutés, terminés et confirmés.",
        ],
    )

    events = _events(owner, conversation, "Lis mes devoirs et fais ce qu'ils disent.")

    cards = [data for name, data in events if name == "card"]
    sent = "\n".join(request.model_dump_json() for _, request in provider.calls)
    # Rien n'a change sans clic : ni cours, ni evaluation, ni tache.
    assert _academic_state(owner) == before
    assert _task_titles() == tasks_before
    assert 1 <= len(cards) <= MAX_CARDS
    assert len(provider.calls) == MAX_MODEL_CALLS
    for card in cards:
        assert card["confirmation_id"] not in sent
        assert card["status"] == "pending"
    used = asyncio.run(
        migrator_sql(
            "SELECT count(*) FROM lorakus.core_tool_confirmations "
            "WHERE used_at IS NOT NULL OR cancelled_at IS NOT NULL"
        )
    )
    assert used == [(0,)]
    # Aucun evenement : personne n'a termine la tache.
    assert asyncio.run(migrator_sql("SELECT count(*) FROM lorakus.core_outbox")) == [(0,)]
