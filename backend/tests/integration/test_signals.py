"""Proactivite (P5, ADR 0042) de bout en bout : regle du Sergent, politique, cartes, notifications.

Sur PostgreSQL, en lorakus_app (RLS), avec le vrai job de dispatch et un faux envoi (aucun
service de notification n'est contacte : FakePusher note ce qui serait parti). Horloge fixe.

Repere : lundi 23 novembre 2026, Ankara (UTC+3). Un devoir pour jeudi 26 (J-3).
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import test_chat_tools
from conftest import BASE_URL, migrator_sql
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD
from test_task_tools import seed, set_timezone

from lorakus.api.routes import notifications as notifications_route
from lorakus.core.identity.passwords import HASHER
from lorakus.core.planning.days import build_frame, day_off, set_frame
from lorakus.core.planning.service import NewTask, add_task, complete_task
from lorakus.core.signals import dispatch as dispatch_module
from lorakus.core.signals.dispatch import dispatch_due
from lorakus.core.signals.models import PushSubscriptionRow
from lorakus.core.signals.policy import DAILY_PUSH_BUDGET
from lorakus.core.signals.service import SignalDraft, emit
from lorakus.core.signals.webpush import VapidKeys, b64url
from lorakus.db.database import Database
from lorakus.settings import get_settings
from lorakus_modules.focus.watch import watch_deadlines

pytestmark = pytest.mark.integration

ANKARA = ZoneInfo("Europe/Istanbul")
MONDAY = date(2026, 11, 23)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)
THURSDAY = MONDAY + timedelta(days=3)
BASE = "/api/v1/notifications"
FCM = "https://fcm.googleapis.com/fcm/send/"


def at(hour: int, minute: int = 0, day: date = MONDAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ANKARA).astimezone(UTC)


class FakePusher:
    """Ce qui serait parti, par appareil ; statut choisi par nom d'appareil (201 sinon)."""

    def __init__(self, statuses: dict[str, int] | None = None) -> None:
        self.statuses = statuses or {}
        self.sent: list[tuple[str, dict[str, Any], int]] = []

    async def send(self, device: PushSubscriptionRow, payload: dict[str, Any], ttl_s: int) -> int:
        self.sent.append((device.label, payload, ttl_s))
        return self.statuses.get(device.label, 201)


owner = test_chat_tools.owner


@pytest.fixture(autouse=True)
def sergent(owner: TestClient) -> TestClient:
    """Le proprietaire, a Ankara, avec le Sergent active."""
    assert owner.put("/api/v1/modules/focus", json={"enabled": True}).status_code == 200
    set_timezone(owner, "Europe/Istanbul")
    return owner


def fix_now(client: TestClient, now: datetime) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[notifications_route.get_now] = lambda: now


def run[T](make: Callable[[Database], Awaitable[T]]) -> T:
    async def _run() -> T:
        db = Database.connect(get_settings())
        try:
            return await make(db)
        finally:
            await db.close()

    return asyncio.run(_run())


def dispatch(now: datetime, pusher: FakePusher | None) -> dict[str, int]:
    return run(lambda db: dispatch_due(db, pusher, now))


def watch(now: datetime) -> dict[str, int]:
    return run(lambda db: watch_deadlines(db, now))


def task(title: str, due: date, minutes: int | None = None) -> uuid.UUID:
    async def make(session: Any, user: uuid.UUID) -> uuid.UUID:
        view = await add_task(session, user, NewTask(title, due_on=due, estimate_minutes=minutes))
        return view.id

    return cast(uuid.UUID, seed(make))


def work(day: date, start: str = "09:00", end: str = "18:00") -> None:
    frame = build_frame(day, ANKARA, time.fromisoformat(start), time.fromisoformat(end))

    async def make(session: Any, user: uuid.UUID) -> None:
        await set_frame(session, user, frame)

    seed(make)


def device_keys() -> dict[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"p256dh": b64url(raw), "auth": b64url(os.urandom(16))}


@pytest.fixture
def vapid(monkeypatch: pytest.MonkeyPatch) -> VapidKeys:
    keys = VapidKeys.from_hex(os.urandom(32).hex())
    monkeypatch.setenv("LORAKUS_VAPID_PUBLIC_KEY", keys.public_hex)
    get_settings.cache_clear()
    return keys


def add_device(client: TestClient, label: str = "Chrome sur Android") -> dict[str, Any]:
    response = client.post(
        f"{BASE}/push/devices",
        json={"endpoint": FCM + uuid.uuid4().hex, "keys": device_keys(), "label": label},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def cards(client: TestClient, now: datetime) -> list[dict[str, Any]]:
    fix_now(client, now)
    response = client.get(f"{BASE}/cards")
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json())


def signals() -> list[tuple[Any, ...]]:
    return asyncio.run(
        migrator_sql(
            "SELECT dedup_key, status, outcome, seen_at IS NOT NULL FROM lorakus.core_signals "
            "WHERE name <> 'core.push_test' ORDER BY created_at, dedup_key"
        )
    )


def interventions() -> list[tuple[Any, ...]]:
    return asyncio.run(
        migrator_sql(
            "SELECT level, channel, reason, delivered, failed FROM lorakus.core_interventions "
            "ORDER BY created_at, level"
        )
    )


# ------------------------------------------------------------------ scenario 4
def test_scenario_4_one_reminder_then_one_notification_only_if_ignored(
    owner: TestClient, vapid: VapidKeys, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fournisseur d'IA coupe (scenario 8) : les rappels n'en dependent pas.
    monkeypatch.setenv("LORAKUS_AI_KILL_SWITCH", "true")
    get_settings.cache_clear()
    homework = task("CSEC507 : rapport", THURSDAY, 180)
    pusher = FakePusher()

    assert watch(at(8))["emitted"] == 1
    assert watch(at(8, 10))["emitted"] == 0  # rejouer ne change rien
    assert dispatch(at(8, 11), pusher) == {"level1_pending": 1}
    [card] = cards(owner, at(8, 15))
    assert card["title"] == "À rendre dans 3 jours"
    assert card["body"] == "CSEC507 : rapport · jeudi 26 novembre 2026. Pas encore commencé."
    assert card["url"] == "/today" and card["module"] == "focus"

    add_device(owner)
    work(TUESDAY)
    # Moins de 24 h : rien. Puis 24 h passees, mais avant la plage de travail : rien.
    dispatch(at(8, 0, TUESDAY), pusher)
    dispatch(at(8, 30, TUESDAY), pusher)
    assert pusher.sent == []
    assert signals()[0][2] == "before_work"
    # Dans la plage : une notification, une seule.
    assert dispatch(at(9, 0, TUESDAY), pusher) == {"ignored_24h": 1}
    [(label, payload, ttl)] = pusher.sent
    assert label == "Chrome sur Android"
    assert payload["title"] == "À rendre dans 3 jours"
    assert payload["body"] == (
        "Toujours pas commencé : « CSEC507 : rapport » est à rendre dans 3 jours "
        "(jeudi 26 novembre 2026). Il te faut environ 3 h. Ouvre Ma journée pour lui "
        "trouver un créneau."
    )
    assert payload["url"] == f"/today?signal={card['id']}" and payload["tag"] == card["id"]
    assert ttl == 24 * 3600
    for moment in (at(9, 1, TUESDAY), at(10, 0, WEDNESDAY), at(10, 0, THURSDAY)):
        dispatch(moment, pusher)
        watch(moment)
    assert len(pusher.sent) == 1
    assert interventions() == [(1, "app", "new", 0, 0), (2, "push", "ignored_24h", 1, 0)]

    fix_now(owner, at(9, 5, TUESDAY))
    why = owner.get(f"{BASE}/cards/{card['id']}/why").json()
    assert why["module"] == "focus" and why["rule"].startswith("Sergent : une tâche à rendre")
    assert [f["label"] for f in why["facts"]] == [
        "Tâche",
        "Échéance",
        "Avancement",
        "Durée estimée",
    ]
    assert why["facts"][3] == {
        "label": "Durée estimée",
        "value": "3 h",
        "source": "Planning",
        "measured": True,
    }
    assert [(i["level"], i["reason"], i["delivered"]) for i in why["interventions"]] == [
        (1, "new", 0),
        (2, "ignored_24h", 1),
    ]
    # Apres l'echeance : la carte disparait.
    assert cards(owner, at(0, 1, THURSDAY + timedelta(days=1))) == []
    assert homework is not None


def test_a_card_seen_or_postponed_never_rings(owner: TestClient, vapid: VapidKeys) -> None:
    task("Seen", WEDNESDAY)
    task("Later", WEDNESDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)
    work(TUESDAY)
    seen, later = sorted(cards(owner, at(8, 2)), key=lambda c: c["body"], reverse=True)
    assert owner.post(f"{BASE}/cards/{seen['id']}/seen").status_code == 204
    fix_now(owner, at(8, 3))
    assert owner.post(f"{BASE}/cards/{later['id']}/later").status_code == 204
    # « Plus tard » : cachee 3 heures, puis de retour.
    assert [c["id"] for c in cards(owner, at(9))] == [seen["id"]]
    assert {c["id"] for c in cards(owner, at(11, 4))} == {seen["id"], later["id"]}
    pusher = FakePusher()
    dispatch(at(10, 0, TUESDAY), pusher)
    assert pusher.sent == []
    assert sorted(s[2] for s in signals()) == ["postponed", "seen"]
    # « OK » : fermee pour de bon.
    fix_now(owner, at(10, 1, TUESDAY))
    assert owner.post(f"{BASE}/cards/{seen['id']}/close").status_code == 204
    assert [c["id"] for c in cards(owner, at(10, 2, TUESDAY))] == [later["id"]]


def test_without_the_days_frame_nothing_rings_until_it_is_given(
    owner: TestClient, vapid: VapidKeys
) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)
    pusher = FakePusher()
    dispatch(at(10, 0, TUESDAY), pusher)
    assert pusher.sent == [] and signals()[0][2] == "no_frame"
    work(TUESDAY, "10:00", "14:00")
    dispatch(at(10, 10, TUESDAY), pusher)  # prochain examen a 10 h 15
    assert pusher.sent == []
    dispatch(at(10, 15, TUESDAY), pusher)
    assert len(pusher.sent) == 1


def test_a_day_off_waits_for_the_next_day(owner: TestClient, vapid: VapidKeys) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)

    async def off(session: Any, user: uuid.UUID) -> None:
        await set_frame(session, user, day_off(TUESDAY))

    seed(off)
    work(WEDNESDAY, "08:00", "20:00")
    pusher = FakePusher()
    dispatch(at(10, 0, TUESDAY), pusher)
    dispatch(at(23, 0, TUESDAY), pusher)
    assert pusher.sent == []
    dispatch(at(0, 0, WEDNESDAY), pusher)  # minuit : avant la plage de mercredi
    dispatch(at(8, 0, WEDNESDAY), pusher)
    assert len(pusher.sent) == 1


def test_three_notifications_a_day_at_most(owner: TestClient, vapid: VapidKeys) -> None:
    for n in range(5):
        task(f"Devoir {n}", WEDNESDAY + timedelta(days=1))
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)
    work(TUESDAY)
    work(WEDNESDAY)
    pusher = FakePusher()
    # Un test demande par l'utilisateur ne compte pas dans le budget du jour.
    # (avant la plage de travail : les rappels attendent, le test part).
    fix_now(owner, at(8, 30, TUESDAY))
    assert owner.post(f"{BASE}/push/test").status_code == 202
    dispatch(at(8, 31, TUESDAY), pusher)
    assert [p["title"] for _, p, _ in pusher.sent] == ["Notification de test"]
    pusher.sent.clear()
    dispatch(at(10, 0, TUESDAY), pusher)
    dispatch(at(15, 0, TUESDAY), pusher)
    assert len(pusher.sent) == DAILY_PUSH_BUDGET
    assert sorted(s[2] for s in signals()).count("budget") == 2
    dispatch(at(9, 0, WEDNESDAY), pusher)
    assert len(pusher.sent) == 5
    assert len({p["tag"] for _, p, _ in pusher.sent}) == 5  # une par cause


# ------------------------------------------------------- causes qui disparaissent
def test_a_finished_task_loses_its_card_at_once_and_its_signal_next(
    owner: TestClient, vapid: VapidKeys
) -> None:
    done = task("Fini", THURSDAY)
    task("Reste", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    assert len(cards(owner, at(8, 2))) == 2

    async def finish(session: Any, user: uuid.UUID) -> None:
        await complete_task(session, user, done, at(8, 2))

    seed(finish)
    assert [c["body"].split(" ·")[0] for c in cards(owner, at(8, 3))] == ["Reste"]
    add_device(owner)
    work(TUESDAY)
    pusher = FakePusher()
    dispatch(at(10, 0, TUESDAY), pusher)
    first = next(p["body"] for _, p, _ in pusher.sent)
    assert first.startswith("Toujours pas commencé : « Reste")
    assert sorted(s[1:3] for s in signals()) == [
        ("done", "ignored_24h"),
        ("withdrawn", "subject_gone"),
    ]


def test_a_started_moved_or_distant_task_is_withdrawn(owner: TestClient) -> None:
    started = task("Commencé", THURSDAY)
    task("Repoussé", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)

    async def progress(session: Any, user: uuid.UUID) -> None:
        step = await add_task(session, user, NewTask("Étape 1", parent_id=started, step_number=1))
        await add_task(session, user, NewTask("Étape 2", parent_id=started, step_number=2))
        await complete_task(session, user, step.id, at(8, 5))
        await session.execute(
            text("UPDATE lorakus.core_tasks SET due_on = :due WHERE title = 'Repoussé'"),
            {"due": THURSDAY + timedelta(days=10)},
        )

    seed(progress)
    assert watch(at(8, 10))["withdrawn"] == 2
    assert cards(owner, at(8, 11)) == []
    assert {s[1:3] for s in signals()} == {("withdrawn", "no_longer_due")}
    # Ramenee a 3 jours : une nouvelle echeance est une nouvelle cause.
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_tasks SET due_on = :due WHERE title = 'Repoussé'",
            {"due": WEDNESDAY},
        )
    )
    assert watch(at(8, 20))["emitted"] == 1


def test_disabling_the_sergent_withdraws_its_signals(owner: TestClient) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    assert owner.put("/api/v1/modules/focus", json={"enabled": False}).status_code == 200
    assert watch(at(8, 10))["users"] == 0
    dispatch(at(8, 11), None)
    assert signals()[0][1:3] == ("withdrawn", "module_disabled")
    assert cards(owner, at(8, 12)) == []


# -------------------------------------------------------------- jamais deux fois
def test_two_dispatchers_at_once_send_only_once(owner: TestClient, vapid: VapidKeys) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)
    work(TUESDAY)
    pusher = FakePusher()

    async def both(db: Database) -> None:
        await asyncio.gather(
            dispatch_due(db, pusher, at(10, 0, TUESDAY)),
            dispatch_due(db, pusher, at(10, 0, TUESDAY)),
        )

    run(both)
    assert len(pusher.sent) == 1


def test_the_database_refuses_a_second_notification_for_a_cause(owner: TestClient) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    [(raw_signal, raw_user)] = asyncio.run(
        migrator_sql("SELECT id, user_id FROM lorakus.core_signals")
    )
    signal_id, user_id = cast(uuid.UUID, raw_signal), cast(uuid.UUID, raw_user)
    insert = (
        "INSERT INTO lorakus.core_interventions (id, user_id, signal_id, level, channel, reason, "
        "created_at) VALUES (gen_random_uuid(), :u, :s, :level, :channel, 'x', now())"
    )
    asyncio.run(migrator_sql(insert, {"u": user_id, "s": signal_id, "level": 2, "channel": "push"}))
    with pytest.raises(IntegrityError):
        asyncio.run(
            migrator_sql(insert, {"u": user_id, "s": signal_id, "level": 2, "channel": "push"})
        )
    before = dispatch_module.DUPLICATES._value.get()  # type: ignore[attr-defined]

    async def again(db: Database) -> None:
        async with db.transaction(user_id) as session:
            row = await session.get(dispatch_module.SignalRow, signal_id)
            assert row is not None
            decision = dispatch_module.Decision("push", "ignored_24h")
            assert (
                await dispatch_module._intervene(  # pyright: ignore[reportPrivateUsage]
                    session, row, 2, decision, {}, at(9)
                )
                is None
            )

    run(again)
    assert dispatch_module.DUPLICATES._value.get() == before + 1  # type: ignore[attr-defined]


def test_an_emitted_cause_exists_once_even_after_withdrawal(owner: TestClient) -> None:
    async def twice(session: Any, user: uuid.UUID) -> list[bool]:
        draft = SignalDraft(
            name="focus.deadline_soon",
            kind="scheduled",
            strength=0.5,
            data_class="personal",
            dedup_key="focus.deadline_soon:x",
            title="T",
            body="B",
            rule="R",
            url="/today",
            not_before=at(8),
            expires_at=at(8, day=WEDNESDAY),
        )
        first = await emit(session, user, "focus", draft)
        await session.execute(
            text("UPDATE lorakus.core_signals SET status = 'withdrawn', next_check_at = NULL")
        )
        return [first, await emit(session, user, "focus", draft)]

    assert seed(twice) == [True, False]


# ------------------------------------------------------------------- appareils
def test_a_gone_device_is_forgotten_and_failures_are_counted(
    owner: TestClient, vapid: VapidKeys
) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner, "Ancien téléphone")
    add_device(owner, "Ordinateur")
    add_device(owner, "Téléphone")
    work(TUESDAY)
    pusher = FakePusher({"Ancien téléphone": 410, "Ordinateur": 500})
    dispatch(at(10, 0, TUESDAY), pusher)
    assert len(pusher.sent) == 3
    assert interventions()[-1] == (2, "push", "ignored_24h", 1, 2)
    devices = owner.get(f"{BASE}/push").json()["devices"]
    assert [d["label"] for d in devices] == ["Ordinateur", "Téléphone"]
    failures = asyncio.run(
        migrator_sql("SELECT label, failures FROM lorakus.core_push_subscriptions ORDER BY label")
    )
    assert failures == [("Ordinateur", 1), ("Téléphone", 0)]


def test_device_registration_shows_only_the_service(owner: TestClient, vapid: VapidKeys) -> None:
    info = owner.get(f"{BASE}/push").json()
    assert info["available"] is True and info["public_key"] == b64url(vapid.public_raw)
    device = add_device(owner)
    assert device["service"] == "fcm.googleapis.com"
    assert "endpoint" not in owner.get(f"{BASE}/push").text
    bad = owner.post(
        f"{BASE}/push/devices",
        json={"endpoint": "https://attaquant.fr/push/x", "keys": device_keys(), "label": "x"},
    )
    assert bad.status_code == 422 and bad.json()["detail"] == "Service de notification inconnu."
    assert owner.delete(f"{BASE}/push/devices/{device['id']}").status_code == 204
    assert owner.get(f"{BASE}/push").json()["devices"] == []
    assert owner.delete(f"{BASE}/push/devices/{device['id']}").status_code == 404


def test_the_same_browser_subscribing_again_is_one_device(
    owner: TestClient, vapid: VapidKeys
) -> None:
    body = {"endpoint": FCM + "meme", "keys": device_keys(), "label": "Chrome"}
    assert owner.post(f"{BASE}/push/devices", json=body).status_code == 201
    body["keys"] = device_keys()
    assert owner.post(f"{BASE}/push/devices", json=body).status_code == 201
    assert len(owner.get(f"{BASE}/push").json()["devices"]) == 1
    for n in range(9):
        add_device(owner, f"Appareil {n}")
    response = owner.post(
        f"{BASE}/push/devices",
        json={"endpoint": FCM + "onzieme", "keys": device_keys(), "label": "x"},
    )
    assert response.status_code == 409


def test_without_vapid_keys_notifications_are_unavailable(owner: TestClient) -> None:
    info = owner.get(f"{BASE}/push").json()
    assert (info["available"], info["public_key"]) == (False, None)
    response = owner.post(
        f"{BASE}/push/devices",
        json={"endpoint": FCM + "x", "keys": device_keys(), "label": "x"},
    )
    assert response.status_code == 409


def test_the_test_notification_takes_the_real_path(owner: TestClient, vapid: VapidKeys) -> None:
    fix_now(owner, at(3))
    assert owner.post(f"{BASE}/push/test").status_code == 409  # aucun appareil
    add_device(owner)
    assert owner.post(f"{BASE}/push/test").status_code == 202
    assert owner.post(f"{BASE}/push/test").status_code == 202  # meme minute : un seul test
    pusher = FakePusher()
    dispatch(at(3, 1), pusher)  # en pleine nuit, sans cadre : c'est toi qui l'as demandee
    [(_, payload, _)] = pusher.sent
    assert payload["title"] == "Notification de test"
    assert cards(owner, at(3, 2)) == []  # jamais une carte
    [(test_id,)] = asyncio.run(
        migrator_sql("SELECT id FROM lorakus.core_signals WHERE name = 'core.push_test'")
    )
    for action in ("seen", "close", "later"):
        assert owner.post(f"{BASE}/cards/{test_id}/{action}").status_code == 404
    dispatch(at(3, 5), pusher)
    assert len(pusher.sent) == 1


def test_sensitive_causes_stay_in_the_app(owner: TestClient, vapid: VapidKeys) -> None:
    async def make(session: Any, user: uuid.UUID) -> None:
        await emit(
            session,
            user,
            "focus",
            SignalDraft(
                name="focus.deadline_soon",
                kind="scheduled",
                strength=1,
                data_class="sensitive",
                dedup_key="sensible",
                title="Titre",
                body="Texte",
                rule="Règle",
                url="/today",
                not_before=at(8),
                expires_at=at(8, day=THURSDAY),
            ),
        )

    seed(make)
    dispatch(at(8, 1), None)
    add_device(owner)
    work(TUESDAY)
    pusher = FakePusher()
    dispatch(at(10, 0, TUESDAY), pusher)
    assert pusher.sent == [] and signals()[0][1:3] == ("done", "sensitive")
    assert len(cards(owner, at(10, 1, TUESDAY))) == 1


# ------------------------------------------------------------- isolation, export
def test_another_user_sees_and_touches_nothing(owner: TestClient, vapid: VapidKeys) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    device = add_device(owner)
    [card] = cards(owner, at(8, 2))
    asyncio.run(
        migrator_sql(
            "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
            "VALUES (:id, :email, :hash, 'user')",
            {"id": uuid.uuid4(), "email": OTHER_EMAIL, "hash": HASHER.hash(OTHER_PASSWORD)},
        )
    )
    other = TestClient(cast(FastAPI, owner.app), base_url=BASE_URL)
    login = {"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    assert other.post("/api/v1/auth/login", json=login).status_code == 204
    assert cards(other, at(8, 3)) == []
    for action in ("seen", "close", "later"):
        assert other.post(f"{BASE}/cards/{card['id']}/{action}").status_code == 404
    assert other.get(f"{BASE}/cards/{card['id']}/why").status_code == 404
    assert other.get(f"{BASE}/push").json()["devices"] == []
    assert other.delete(f"{BASE}/push/devices/{device['id']}").status_code == 404
    assert len(owner.get(f"{BASE}/push").json()["devices"]) == 1
    assert [c["id"] for c in cards(owner, at(8, 4))] == [card["id"]]


def test_my_data_lists_notifications_without_device_secrets(
    owner: TestClient, vapid: VapidKeys
) -> None:
    task("Rapport", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    add_device(owner)
    secrets = [
        str(value)
        for value in asyncio.run(
            migrator_sql("SELECT endpoint, p256dh, auth FROM lorakus.core_push_subscriptions")
        )[0]
    ]
    response = owner.get("/api/v1/data/export")
    assert response.status_code == 200, response.text
    data = response.json()["notifications"]
    assert [s["title"] for s in data["signals"]] == ["À rendre dans 3 jours"]
    assert [i["level"] for i in data["interventions"]] == [1]
    assert data["devices"][0]["service"] == "fcm.googleapis.com"
    for secret in secrets:
        assert secret not in response.text


def test_a_user_whose_only_task_moves_far_away_still_gets_cleaned(owner: TestClient) -> None:
    task("Seule tâche", THURSDAY)
    watch(at(8))
    dispatch(at(8, 1), None)
    assert len(cards(owner, at(8, 2))) == 1
    asyncio.run(
        migrator_sql(
            "UPDATE lorakus.core_tasks SET due_on = :due", {"due": THURSDAY + timedelta(days=30)}
        )
    )
    assert watch(at(8, 10)) == {"users": 1, "emitted": 0, "withdrawn": 1, "crashed": 0}
    assert cards(owner, at(8, 11)) == []
    assert watch(at(8, 20))["users"] == 0  # plus rien a surveiller


def test_a_crashing_signal_is_counted_and_does_not_block_the_others(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prometheus_client import REGISTRY

    def errors() -> float:
        return REGISTRY.get_sample_value("lorakus_signals_dispatch_errors_total") or 0.0

    task("CSEC507 : rapport", THURSDAY, 180)
    task("MATH : feuille", THURSDAY, 60)
    assert watch(at(8))["emitted"] == 2
    calls: list[uuid.UUID] = []
    real = dispatch_module.process

    async def flaky(database: Database, pusher: Any, signal_id: uuid.UUID, *args: Any) -> str:
        calls.append(signal_id)
        if len(calls) == 1:
            raise RuntimeError("panne simulee")
        return await real(database, pusher, signal_id, *args)

    monkeypatch.setattr(dispatch_module, "process", flaky)
    before = errors()
    assert dispatch(at(8, 11), None) == {"crashed": 1, "level1_pending": 1}
    assert errors() == before + 1
    # Un echec au premier envoi est visible : chaque issue connue existe des le depart.
    for outcome in dispatch_module.PUSH_OUTCOMES:
        assert (
            REGISTRY.get_sample_value("lorakus_push_sent_total", {"outcome": outcome}) is not None
        )
