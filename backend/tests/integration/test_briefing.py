"""Briefing du lendemain (P5, scenario 3) : prepare quand la journee est finie, un seul par
jour, rafraichi jusqu'a sa lecture, puis fige ; jamais montre une fois expire.

Sur PostgreSQL, en lorakus_app (RLS), avec le vrai job. Horloge fixe : lundi 23 novembre
2026, Ankara (UTC+3).
"""

import asyncio
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, cast

import pytest
from conftest import BASE_URL, migrator_sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_tools import OTHER_EMAIL, OTHER_PASSWORD
from test_signals import (
    ANKARA,
    MONDAY,
    THURSDAY,
    TUESDAY,
    WEDNESDAY,
    at,
    owner,
    run,
    sergent,
    task,
    work,
)
from test_task_tools import seed

from lorakus.api.routes import preparations as preparations_route
from lorakus.core.identity.passwords import HASHER
from lorakus.core.planning.days import BreakKind, build_frame, day_off, set_frame
from lorakus.core.planning.service import AgendaItem, ModuleAgenda
from lorakus_modules.focus.briefing import prepare_all

pytestmark = pytest.mark.integration
__all__ = ["owner", "sergent"]  # fixtures partagees avec test_signals

BASE = "/api/v1/preparations"
SATURDAY = MONDAY - timedelta(days=2)


def prepare(now: datetime) -> dict[str, int]:
    return run(lambda db: prepare_all(db, now))


def shown(client: TestClient, now: datetime) -> list[dict[str, Any]]:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[preparations_route.get_now] = lambda: now
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json())


def sections(preparation: dict[str, Any]) -> dict[str, list[str]]:
    return {s["heading"]: s["lines"] for s in preparation["sections"]}


def rows() -> list[tuple[Any, ...]]:
    return asyncio.run(
        migrator_sql("SELECT day, status, prepared_at FROM lorakus.core_preparations ORDER BY day")
    )


def agenda(*items: AgendaItem) -> None:
    async def make(session: Any, user: uuid.UUID) -> None:
        await ModuleAgenda("calendars").replace_source(session, user, "cours", list(items))

    seed(make)


def day_frame(day: date, start: str, end: str, meal: tuple[str, str] | None = None) -> None:
    breaks: list[tuple[BreakKind, time, time]] = (
        [("meal", time.fromisoformat(meal[0]), time.fromisoformat(meal[1]))] if meal else []
    )
    frame = build_frame(day, ANKARA, time.fromisoformat(start), time.fromisoformat(end), breaks)

    async def make(session: Any, user: uuid.UUID) -> None:
        await set_frame(session, user, frame)

    seed(make)


def test_scenario_3_tomorrow_is_prepared_once_today_is_over(owner: TestClient) -> None:
    work(MONDAY)  # 9 h - 18 h
    agenda(
        AgendaItem("c1", "CSEC 507", at(8, 40, TUESDAY), at(10, 30, TUESDAY), location="A-101"),
        AgendaItem("c2", "Machine Learning", at(13, 40, TUESDAY), at(15, 30, TUESDAY)),
        AgendaItem("sport", "Tournoi d'échecs", start_date=TUESDAY, end_date=WEDNESDAY),
        AgendaItem("ferie", "Journée sans cours", start_date=WEDNESDAY, end_date=THURSDAY),
    )
    task("Rapport CSEC507", WEDNESDAY, 120)
    task("Vieux devoir", SATURDAY)
    task("Exercice du jour", MONDAY, 30)
    task("Partiel à réviser", THURSDAY)

    # Pendant la journee de lundi : c'est le briefing de lundi qui est tenu a jour.
    prepare(at(17))
    assert [r[0] for r in rows()] == [MONDAY]
    # Plage finie (18 h pile) : celui de mardi est prepare, et lui seul est montre.
    assert prepare(at(18))["prepared"] == 1
    assert [r[0] for r in rows()] == [MONDAY, TUESDAY]
    [briefing] = shown(owner, at(18, 20))
    assert briefing["title"] == "Mardi 24 novembre 2026" and briefing["day"] == "2026-11-24"
    assert briefing["module"] == "focus" and briefing["kind"] == "briefing"
    content = sections(briefing)
    assert list(content) == ["Agenda", "Ta journée", "Échéances", "En retard"]
    assert content["Agenda"] == [
        "Toute la journée · Tournoi d'échecs",
        "08:40 - 10:30 · CSEC 507 · A-101",
        "13:40 - 15:30 · Machine Learning",
    ]
    assert content["Ta journée"] == [
        "Pas encore décrite : dis-moi dans le chat quand tu travailles, et je placerai tes tâches."
    ]
    assert content["Échéances"] == [
        "Rapport CSEC507 · mercredi 25 novembre 2026 (demain)",
        "Partiel à réviser · jeudi 26 novembre 2026 (dans 2 jours)",
    ]
    # Ecrit du point de vue de mardi : ce qui etait du lundi sera en retard au reveil.
    assert content["En retard"] == [
        "Vieux devoir · samedi 21 novembre 2026 (il y a 3 jours)",
        "Exercice du jour · lundi 23 novembre 2026 (hier)",
    ]

    # Tant qu'il n'est pas lu, il suit l'agenda et les taches : toujours un seul pour mardi.
    day_frame(TUESDAY, "09:00", "18:00", ("12:00", "13:00"))
    prepare(at(22))
    [briefing] = shown(owner, at(22, 5))
    assert sections(briefing)["Ta journée"] == [
        "Travail de 09:00 à 18:00, pauses 12:00 - 13:00.",
        "Proposé : 2 h 30 de travail.",
        "10:30 - 11:00 · Exercice du jour",
        "11:15 - 12:00 · Rapport CSEC507",
        "13:00 - 13:40 · Rapport CSEC507",
        "15:30 - 16:05 · Rapport CSEC507",
        "2 tâches sans durée : dis-moi combien de temps elles prendront.",
    ]
    assert [r[0] for r in rows()] == [MONDAY, TUESDAY]

    # Lu : fige et cache ; le refaire n'y change rien.
    app = cast(FastAPI, owner.app)
    app.dependency_overrides[preparations_route.get_now] = lambda: at(7, day=TUESDAY)
    assert owner.post(f"{BASE}/{briefing['id']}/consulted").status_code == 204
    assert owner.post(f"{BASE}/{briefing['id']}/consulted").status_code == 204
    frozen = rows()[1][2]
    assert prepare(at(7, 30, TUESDAY))["prepared"] == 0
    assert rows()[1][1:] == ("consulted", frozen)
    assert shown(owner, at(7, 31, TUESDAY)) == []


def test_without_a_frame_the_day_is_prepared_from_midnight(owner: TestClient) -> None:
    prepare(at(0, 5))
    prepare(at(23))
    assert [r[0] for r in rows()] == [MONDAY]  # sans plage, pas de « lendemain » le soir
    [briefing] = shown(owner, at(23, 1))
    assert briefing["day"] == "2026-11-23"
    prepare(at(0, 5, TUESDAY))
    assert [r[0] for r in rows()] == [MONDAY, TUESDAY]
    assert [b["day"] for b in shown(owner, at(0, 6, TUESDAY))] == ["2026-11-24"]


def test_a_day_off_waits_for_midnight(owner: TestClient) -> None:
    async def off(session: Any, user: uuid.UUID) -> None:
        await set_frame(session, user, day_off(MONDAY))

    seed(off)
    prepare(at(20))
    content = sections(shown(owner, at(20, 1))[0])
    assert content["Ta journée"] == ["Jour sans travail : rien n'est proposé."]
    assert [r[0] for r in rows()] == [MONDAY]


def test_a_night_of_work_belongs_to_the_day_it_started(owner: TestClient) -> None:
    day_frame(MONDAY, "22:00", "04:00")
    prepare(at(2, 0, TUESDAY))  # encore la nuit de lundi
    assert [r[0] for r in rows()] == [MONDAY]
    prepare(at(4, 15, TUESDAY))  # nuit finie : mardi
    assert [r[0] for r in rows()] == [MONDAY, TUESDAY]
    # Le briefing de lundi valait jusqu'a la fin de la nuit, pas jusqu'a minuit.
    expiry = asyncio.run(
        migrator_sql(
            "SELECT expires_at FROM lorakus.core_preparations WHERE day = :d", {"d": MONDAY}
        )
    )[0][0]
    assert expiry == at(4, 0, TUESDAY)


def test_an_expired_briefing_is_never_shown(owner: TestClient) -> None:
    work(MONDAY)
    prepare(at(18, 30))
    assert len(shown(owner, at(23, 59, TUESDAY))) == 1
    assert shown(owner, at(0, 0, WEDNESDAY)) == []


def test_long_lists_are_counted_not_hidden(owner: TestClient) -> None:
    day_frame(MONDAY, "08:00", "20:00")
    for n in range(8):
        task(f"Devoir {n}", TUESDAY, 30)
    prepare(at(0, 5))
    content = sections(shown(owner, at(0, 6))[0])
    deadlines = content["Échéances"]
    assert len(deadlines) == 6 and deadlines[-1] == "… et 3 autres échéances."
    day = content["Ta journée"]
    assert len(day) == 2 + 4 + 1 and day[-1] == "… et 4 autres créneaux proposés."


def test_only_for_users_of_the_sergent(owner: TestClient) -> None:
    assert owner.put("/api/v1/modules/focus", json={"enabled": False}).status_code == 200
    assert prepare(at(0, 5)) == {"users": 0, "prepared": 0, "crashed": 0}
    assert rows() == []


def test_another_user_sees_and_reads_nothing(owner: TestClient) -> None:
    prepare(at(0, 5))
    [briefing] = shown(owner, at(0, 6))
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
    assert shown(other, at(0, 7)) == []
    assert other.post(f"{BASE}/{briefing['id']}/consulted").status_code == 404
    assert len(shown(owner, at(0, 8))) == 1


def test_my_data_lists_the_briefings(owner: TestClient) -> None:
    prepare(at(0, 5))
    response = owner.get("/api/v1/data/export")
    assert response.status_code == 200, response.text
    [briefing] = response.json()["notifications"]["preparations"]
    assert briefing["kind"] == "briefing" and briefing["status"] == "ready"
    assert briefing["title"] == "Lundi 23 novembre 2026"


def test_one_task_without_duration_and_nothing_to_place(owner: TestClient) -> None:
    day_frame(MONDAY, "09:00", "11:00")
    task("Sans durée", TUESDAY)
    prepare(at(0, 5))
    assert sections(shown(owner, at(0, 6))[0])["Ta journée"] == [
        "Travail de 09:00 à 11:00.",
        "Rien à placer dans ta plage de travail.",
        "1 tâche sans durée : dis-moi combien de temps elle prendra.",
    ]


def test_the_edges_of_the_lists(owner: TestClient) -> None:
    """Briefing de mardi : du du jour (pas en retard), J+3 montre, J+4 non ; 6 echeances
    tiennent sans « … » ; au-dela de 4 creneaux, le reste est compte (au singulier pour 1)."""
    day_frame(MONDAY, "09:00", "11:00")
    day_frame(TUESDAY, "08:00", "20:00")
    task("Pour mardi", TUESDAY, 30)
    task("Dans 3 jours", TUESDAY + timedelta(days=3), 30)
    task("Dans 4 jours", TUESDAY + timedelta(days=4), 30)
    for n in range(4):
        task(f"Devoir {n}", WEDNESDAY, 30)
    prepare(at(11, 30))  # plage de lundi finie : mardi
    content = sections(shown(owner, at(11, 31))[0])
    assert "En retard" not in content
    deadlines = content["Échéances"]
    assert len(deadlines) == 6 and not any(line.startswith("…") for line in deadlines)
    assert deadlines[0] == "Pour mardi · mardi 24 novembre 2026 (aujourd'hui)"
    assert deadlines[-1] == "Dans 3 jours · vendredi 27 novembre 2026 (dans 3 jours)"
    day = content["Ta journée"]
    assert day[-1] == "… et 3 autres créneaux proposés."  # 7 taches placees
    asyncio.run(
        migrator_sql("DELETE FROM lorakus.core_tasks WHERE title IN ('Devoir 2', 'Devoir 3')")
    )
    prepare(at(11, 40))
    assert (
        sections(shown(owner, at(11, 41))[0])["Ta journée"][-1] == "… et 1 autre créneau proposé."
    )
