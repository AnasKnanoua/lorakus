"""PR 35 : limites par utilisateur (PostgreSQL) et double authentification obligatoire."""

import asyncio
import re
import time
import uuid
from datetime import UTC, datetime

import pytest
from conftest import BASE_URL, OWNER_EMAIL, OWNER_PASSWORD, create_user_sync, migrator_sql
from fastapi.testclient import TestClient
from sqlalchemy import text

from lorakus import cli
from lorakus.api.app import create_app
from lorakus.core.identity import totp
from lorakus.core.identity.service import IdentityService
from lorakus.core.ratelimit.service import AICallQuota, Limit, RateLimiter
from lorakus.db.database import Database
from lorakus.settings import get_settings

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login"


def _sql(sql: str, params: dict[str, object] | None = None) -> list[tuple[object, ...]]:
    return asyncio.run(migrator_sql(sql, params))


class Clock:
    def __init__(self, at: float) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return datetime.fromtimestamp(self.at, UTC)


# ------------------------------------------------------------------ limites de debit
@pytest.mark.anyio
async def test_limiter_counts_per_window_and_says_when_to_retry(
    database: Database, identity: IdentityService
) -> None:
    user = await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    clock = Clock(1_800_000_000 + 10)  # 10 s apres le debut d'une minute
    limiter = RateLimiter(database, clock)
    limit = [Limit("test", 60, 2)]

    assert (await limiter.hit(user, limit)).allowed
    assert (await limiter.hit(user, limit)).allowed
    refused = await limiter.hit(user, limit)
    assert not refused.allowed
    assert (refused.retry_after, refused.bucket) == (50, "test")

    clock.at += 60  # minute suivante : compteur neuf, l'ancienne fenetre est effacee
    assert (await limiter.hit(user, limit)).allowed
    rows = await migrator_sql("SELECT hits FROM lorakus.core_rate_limits WHERE bucket = 'test'")
    assert rows == [(1,)]


@pytest.mark.anyio
async def test_limiter_counters_are_isolated_by_rls(
    database: Database, identity: IdentityService
) -> None:
    owner = await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    other = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'autre@example.com', 'x', 'user')",
        {"id": other},
    )
    limiter = RateLimiter(database)
    one = [Limit("solo", 3600, 1)]

    assert (await limiter.hit(owner, one)).allowed
    assert not (await limiter.hit(owner, one)).allowed
    assert (await limiter.hit(other, one)).allowed  # le compteur d'un autre ne compte pas

    async with database.transaction(owner) as session:
        visible = (
            await session.execute(text("SELECT DISTINCT user_id FROM lorakus.core_rate_limits"))
        ).all()
    assert [row[0] for row in visible] == [owner]


@pytest.mark.anyio
async def test_ai_quota_per_minute(database: Database, identity: IdentityService) -> None:
    user = await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    quota = AICallQuota(RateLimiter(database), per_minute=2, per_day=100)
    assert [await quota.allow(user) for _ in range(3)] == [True, True, False]


def test_api_answers_429_with_retry_after(monkeypatch: pytest.MonkeyPatch, api: TestClient) -> None:
    monkeypatch.setenv("LORAKUS_API_REQUESTS_PER_MINUTE", "3")
    get_settings.cache_clear()  # la fixture api a deja lu les parametres
    create_user_sync()
    with TestClient(create_app(), base_url=BASE_URL) as client:
        assert (
            client.post(LOGIN, json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}).status_code
            == 204
        )
        codes = [client.get("/api/v1/auth/me").status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200]
        assert codes[3] == 429
        last = client.get("/api/v1/auth/me")
        assert last.json()["detail"]["code"] == "rate_limited"
        assert 1 <= int(last.headers["Retry-After"]) <= 60


# ------------------------------------------------------------------ double authentification
@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch, api: TestClient) -> TestClient:
    """Application qui exige la double authentification (comme la production)."""
    monkeypatch.setenv("LORAKUS_REQUIRE_SECOND_FACTOR", "true")
    get_settings.cache_clear()
    create_user_sync()
    return TestClient(create_app(), base_url=BASE_URL)


def test_login_without_second_factor_is_refused_when_mandatory(strict: TestClient) -> None:
    with strict:
        response = strict.post(LOGIN, json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "second_factor_setup_required"
    assert "set-cookie" not in response.headers
    assert _sql("SELECT count(*) FROM lorakus.core_sessions") == [(0,)]
    # Un mauvais mot de passe reste un simple echec, sans indice.
    with strict:
        wrong = strict.post(LOGIN, json={"email": OWNER_EMAIL, "password": "pas le bon du tout"})
    assert wrong.status_code == 401


def test_old_session_without_second_factor_stops_working(
    monkeypatch: pytest.MonkeyPatch, api: TestClient
) -> None:
    create_user_sync()
    # Session ouverte avant que la double authentification ne devienne obligatoire.
    assert (
        api.post(LOGIN, json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}).status_code == 204
    )
    cookies = dict(api.cookies)

    monkeypatch.setenv("LORAKUS_REQUIRE_SECOND_FACTOR", "true")
    get_settings.cache_clear()
    with TestClient(create_app(), base_url=BASE_URL, cookies=cookies) as strict:
        assert strict.get("/api/v1/auth/me").status_code == 401
    assert _sql("SELECT count(*) FROM lorakus.core_sessions") == [(0,)]


def test_cli_enables_second_factor_then_login_works_and_cannot_disable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], strict: TestClient
) -> None:
    def fake_input(prompt: str) -> str:
        if prompt.startswith("Adresse"):
            return OWNER_EMAIL
        key = re.search(r"^  ([A-Z2-7 ]{16,})$", capsys.readouterr().out, re.MULTILINE)
        assert key is not None
        secret = key.group(1).replace(" ", "")
        fake_input.secret = secret  # type: ignore[attr-defined]
        return totp.code_at(secret, totp.current_step(time.time()))

    monkeypatch.setattr("builtins.input", fake_input)
    assert cli.main(["enable-second-factor"]) == 0
    assert "Codes de secours" in capsys.readouterr().out
    assert cli.main(["enable-second-factor"]) == 1  # deja active

    secret: str = fake_input.secret  # type: ignore[attr-defined]
    _sql("UPDATE lorakus.core_totp SET last_used_step = NULL")  # le meme code peut resservir ici
    code = totp.code_at(secret, totp.current_step(time.time()))
    with strict:
        body = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD, "second_factor": code}
        assert strict.post(LOGIN, json=body).status_code == 204
        assert strict.get("/api/v1/auth/me").json()["totp_enabled"] is True
        disable = strict.post("/api/v1/auth/totp/disable")
        assert disable.status_code == 409
        assert disable.json()["detail"]["code"] == "second_factor_mandatory"
    assert _sql("SELECT count(*) FROM lorakus.core_totp WHERE confirmed_at IS NOT NULL") == [(1,)]
