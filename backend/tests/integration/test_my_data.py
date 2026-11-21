"""Mes donnees (PR 41) : export complet et suppression de toutes les conversations.

- l'export contient tout (compte, modules, souvenirs, IA, cles, journal, conversations) et
  AUCUN secret reel : ni mot de passe, ni secret ou code de double authentification, ni cle
  d'API, ni jeton de session, ni le nom d'un champ secret ;
- il exige une preuve d'identite recente et ne montre que les donnees de l'utilisateur ;
- supprimer toutes les conversations garde les souvenirs, annule les cartes en attente,
  efface leurs arguments et n'inscrit au journal que le nombre.
"""

import asyncio
import json
import time
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

from lorakus.ai.catalog import Catalog
from lorakus.ai.router import ModelRouter
from lorakus.ai.testing import FakeProvider, FakeReply
from lorakus.ai.usage import UsageStore
from lorakus.api.app import create_app
from lorakus.api.auth import SESSION_COOKIE
from lorakus.core.identity import totp
from lorakus.core.identity.passwords import HASHER
from lorakus.core.ratelimit.service import AICallQuota

pytestmark = pytest.mark.integration

EXPORT = "/api/v1/data/export"
CONVERSATIONS = "/api/v1/assistant/conversations"
REMEMBER = "assistant__remember"
SECRET_FIELDS = (
    "argon2",
    "password_hash",
    "key_hash",
    "token_hash",
    "secret_encrypted",
    "code_hash",
    "embedding",
    "url_ciphertext",  # adresse ICS chiffree (PR 45)
    "url_digest",
)
OTHER_EMAIL = "autre@example.com"
OTHER_PASSWORD = "un autre mot de passe long"


def _sql(sql: str, params: dict[str, object] | None = None) -> list[tuple[object, ...]]:
    return asyncio.run(migrator_sql(sql, params))


def _use_model(client: TestClient, *replies: str | FakeReply) -> None:
    app = cast(FastAPI, client.app)
    app.state.ai = ModelRouter(
        Catalog.load(),
        {"fake": FakeProvider(replies=list(replies))},
        UsageStore(app.state.database),
        monthly_budget_usd=Decimal(3),
        quota=AICallQuota(app.state.rate_limiter, per_minute=30, per_day=200),
    )


def _send(client: TestClient, conversation: str, text: str) -> list[dict[str, Any]]:
    """Envoie un message ; renvoie les cartes du flux."""
    with client.stream(
        "POST", f"{CONVERSATIONS}/{conversation}/messages", json={"content": text}
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    cards: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n")
        if name == "event: card":
            cards.append(json.loads(data.removeprefix("data: ")))
    return cards


def _stale_proof() -> None:
    _sql("UPDATE lorakus.core_sessions SET reauthenticated_at = now() - interval '11 minutes'")


@pytest.fixture
def owner() -> Iterator[TestClient]:
    asyncio.run(wipe_identity())
    with TestClient(create_app(), base_url=BASE_URL) as client:
        create_user_sync()
        login = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        assert client.post("/api/v1/auth/login", json=login).status_code == 204
        assert client.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
        yield client


# ---------------------------------------------------------------------- export
def test_the_export_holds_everything_and_no_real_secret(owner: TestClient) -> None:
    # Secrets reels : double authentification, codes de secours, cle d'API, session.
    secret = owner.post("/api/v1/auth/totp/setup").json()["secret"]
    code = totp.code_at(secret, totp.current_step(time.time()))
    confirmed = owner.post("/api/v1/auth/totp/confirm", json={"code": code})
    backup_codes: list[str] = confirmed.json()["backup_codes"]
    created = owner.post(
        "/api/v1/auth/api-keys",
        json={"name": "telephone", "scopes": ["inbox:write"], "expires_in_days": 30},
    ).json()
    api_key = str(created["key"])
    session_token = owner.cookies.get(SESSION_COOKIE)
    assert session_token
    # Donnees : un souvenir, une conversation avec une carte, des appels au modele.
    owner.post("/api/v1/memory/facts", json={"content": "Révise le matin", "category": "habit"})
    conversation = owner.post(CONVERSATIONS).json()["id"]
    _use_model(
        owner,
        FakeReply("Je te le propose.", tool_calls=((REMEMBER, {"content": "Aime le thé"}),)),
        "Confirme-le ci-dessous.",
    )
    _send(owner, conversation, "Retiens que j'aime le thé")

    response = owner.get(EXPORT)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="lorakus-export-'
    )
    raw = response.text
    data = response.json()
    assert data["format"] == 1
    assert data["account"]["email"] == OWNER_EMAIL
    assert data["account"]["second_factor_enabled"] is True
    assert data["account"]["backup_codes_remaining"] == 10
    # Tous les modules connus, actives ou non (calendars : PR 45 ; academic : PR 46).
    assert [m["id"] for m in data["modules"]] == ["academic", "assistant", "calendars", "focus"]
    assert [f["content"] for f in data["memory"]["facts"]] == ["Révise le matin"]
    assert data["memory"]["settings"] == {"propose_after_conversations": True}
    assert data["ai_usage"][0]["task"] == "chat" and data["ai_usage"][0]["calls"] == 2
    assert [k["name"] for k in data["api_keys"]] == ["telephone"]
    actions = {e["action"] for e in data["security_log"]}
    assert {"auth.login", "auth.totp_enable", "auth.api_key_create"} <= actions
    chats = data["modules_data"]["assistant"]["conversations"]
    assert [c["id"] for c in chats] == [conversation]
    assert [m["role"] for m in chats[0]["messages"]] == ["user", "assistant"]
    assert chats[0]["messages"][1]["actions"][0]["kind"] == "card"
    assert chats[0]["messages"][1]["trace"]["prompt_version"]

    # Aucun secret reel, et aucun champ secret.
    for value in [OWNER_PASSWORD, secret, api_key, session_token, *backup_codes]:
        assert value not in raw, value
    assert api_key.split("_")[-1] not in raw  # meme pas la partie secrete de la cle
    for name in SECRET_FIELDS:
        assert name not in raw, name
    for match in [w for w in raw.replace('"', " ").split() if "token" in w]:
        assert match.startswith(("input_tokens", "output_tokens")), match

    # L'export est journalise, sans contenu.
    [(details,)] = _sql(
        "SELECT details FROM lorakus.core_audit_events WHERE action = 'data.export'"
    )
    assert details == {"modules": ["academic", "assistant", "calendars"]}


def test_the_export_needs_a_recent_proof_of_identity(owner: TestClient) -> None:
    _stale_proof()
    refused = owner.get(EXPORT)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "reauth_required"
    assert _sql("SELECT count(*) FROM lorakus.core_audit_events WHERE action = 'data.export'") == [
        (0,)
    ]
    assert owner.post("/api/v1/auth/reauth", json={"password": OWNER_PASSWORD}).status_code == 204
    assert owner.get(EXPORT).status_code == 200


def test_the_export_holds_a_disabled_module_and_only_my_data(owner: TestClient) -> None:
    owner.post("/api/v1/memory/facts", json={"content": "Aime le thé", "category": "preference"})
    mine = owner.post(CONVERSATIONS).json()["id"]
    _sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, :email, :hash, 'user')",
        {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
    )
    other = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    login = {"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    assert other.post("/api/v1/auth/login", json=login).status_code == 204
    assert other.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
    other.post("/api/v1/memory/facts", json={"content": "Joue au tennis", "category": "habit"})
    theirs = other.post(CONVERSATIONS).json()["id"]
    # Desactiver un module ne supprime pas ses donnees : elles restent dans l'export.
    assert owner.put("/api/v1/modules/assistant", json={"enabled": False}).status_code == 200

    raw = owner.get(EXPORT).text
    data = json.loads(raw)

    enabled = {m["id"]: m["enabled"] for m in data["modules"]}
    assert enabled["assistant"] is False
    assert [c["id"] for c in data["modules_data"]["assistant"]["conversations"]] == [mine]
    assert theirs not in raw and OTHER_EMAIL not in raw and "tennis" not in raw
    their_data = other.get(EXPORT).json()
    assert [f["content"] for f in their_data["memory"]["facts"]] == ["Joue au tennis"]
    assert mine not in json.dumps(their_data)


# ------------------------------------------------- toutes les conversations
def test_deleting_every_conversation_keeps_memories_and_retires_cards(
    owner: TestClient,
) -> None:
    owner.post("/api/v1/memory/facts", json={"content": "Révise le matin", "category": "habit"})
    first, second = (owner.post(CONVERSATIONS).json()["id"] for _ in range(2))
    _use_model(owner, FakeReply("", tool_calls=((REMEMBER, {"content": "Aime le thé"}),)), "OK.")
    [card] = _send(owner, first, "Retiens que j'aime le thé")
    _use_model(owner, "Bonjour.")
    _send(owner, second, "Salut")

    response = owner.delete(CONVERSATIONS)

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert owner.get(CONVERSATIONS).json() == []
    assert _sql("SELECT count(*) FROM lorakus.asst_messages") == [(0,)]
    # Souvenirs intacts ; la carte en attente ne peut plus etre confirmee, sans arguments.
    facts = owner.get("/api/v1/memory/facts").json()
    assert [f["content"] for f in facts] == ["Révise le matin"]
    url = f"/api/v1/tools/confirmations/{card['confirmation_id']}"
    assert owner.post(url).status_code == 409
    assert "thé" not in str(_sql("SELECT arguments::text FROM lorakus.core_tool_confirmations"))
    # Journal : le nombre seulement.
    [(details,)] = _sql(
        "SELECT details FROM lorakus.core_audit_events "
        "WHERE action = 'assistant.conversations.delete_all'"
    )
    assert details == {"count": 2}


def test_deleting_every_conversation_needs_a_recent_proof_and_spares_others(
    owner: TestClient,
) -> None:
    owner.post(CONVERSATIONS)
    _stale_proof()
    refused = owner.delete(CONVERSATIONS)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "reauth_required"
    assert len(owner.get(CONVERSATIONS).json()) == 1

    _sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, :email, :hash, 'user')",
        {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
    )
    other = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    login = {"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    assert other.post("/api/v1/auth/login", json=login).status_code == 204
    assert other.put("/api/v1/modules/assistant", json={"enabled": True}).status_code == 200
    assert other.delete(CONVERSATIONS).json() == {"deleted": 0}
    assert len(owner.get(CONVERSATIONS).json()) == 1  # celles du proprietaire restent
