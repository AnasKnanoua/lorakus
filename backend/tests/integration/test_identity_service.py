"""Service d'identite : mots de passe, re-hachage, limitation par IP, proprietaire."""

import pytest
from argon2 import PasswordHasher
from conftest import OWNER_EMAIL, OWNER_PASSWORD, migrator_sql

from lorakus.core.identity import passwords, service
from lorakus.core.identity.passwords import HASHER, OWASP_MIN_MEMORY_KIB, OWASP_MIN_TIME_COST
from lorakus.core.identity.service import (
    IdentityService,
    InvalidCredentialsError,
    OwnerAlreadyExistsError,
    TooManyAttemptsError,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def test_argon2id_parameters_meet_owasp_minimum() -> None:
    assert HASHER.type.name == "ID"
    assert HASHER.memory_cost >= OWASP_MIN_MEMORY_KIB
    assert HASHER.time_cost >= OWASP_MIN_TIME_COST
    assert HASHER.parallelism >= 1
    assert HASHER.hash("x").startswith("$argon2id$")


async def test_weak_hash_is_upgraded_at_login(identity: IdentityService) -> None:
    await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    weak = PasswordHasher(time_cost=2, memory_cost=OWASP_MIN_MEMORY_KIB, parallelism=1)
    await migrator_sql(
        "UPDATE lorakus.core_users SET password_hash = :h", {"h": weak.hash(OWNER_PASSWORD)}
    )

    await identity.login(OWNER_EMAIL, OWNER_PASSWORD, None)

    [(stored,)] = await migrator_sql("SELECT password_hash FROM lorakus.core_users")
    assert isinstance(stored, str)
    assert not HASHER.check_needs_rehash(stored)
    HASHER.verify(stored, OWNER_PASSWORD)


async def test_a_password_is_verified_exactly_once_on_both_paths(
    identity: IdentityService, monkeypatch: pytest.MonkeyPatch
) -> None:
    await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    calls: list[str] = []
    real_verify = passwords.verify_password

    async def spy(stored_hash: str, password: str) -> passwords.Verification:
        calls.append(stored_hash)
        return await real_verify(stored_hash, password)

    monkeypatch.setattr(service, "verify_password", spy)
    for email in (OWNER_EMAIL, "inconnu@example.com"):
        with pytest.raises(InvalidCredentialsError):
            await identity.login(email, "mauvais mot de passe", None)
    assert len(calls) == 2
    assert calls[1] == passwords.dummy_hash()


async def test_ip_is_limited_across_accounts(identity: IdentityService) -> None:
    ip = "203.0.113.7"
    for number in range(20):
        with pytest.raises(InvalidCredentialsError):
            await identity.login(f"essai{number}@example.com", "mauvais mot de passe", ip)
    with pytest.raises(TooManyAttemptsError):
        await identity.login("encore@example.com", "mauvais mot de passe", ip)
    # Une autre adresse n'est pas touchee.
    with pytest.raises(InvalidCredentialsError):
        await identity.login("encore@example.com", "mauvais mot de passe", "203.0.113.8")


async def test_inactive_account_cannot_log_in(identity: IdentityService) -> None:
    await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    await migrator_sql("UPDATE lorakus.core_users SET is_active = false")
    with pytest.raises(InvalidCredentialsError):
        await identity.login(OWNER_EMAIL, OWNER_PASSWORD, None)


async def test_only_one_owner(identity: IdentityService) -> None:
    await identity.create_owner(OWNER_EMAIL, OWNER_PASSWORD)
    with pytest.raises(OwnerAlreadyExistsError):
        await identity.create_owner("autre@example.com", OWNER_PASSWORD)


async def test_old_failed_attempts_are_purged(identity: IdentityService) -> None:
    await migrator_sql(
        "INSERT INTO lorakus.core_login_attempts (email, attempted_at) "
        "VALUES ('vieux@example.com', now() - interval '2 days')"
    )
    with pytest.raises(InvalidCredentialsError):
        await identity.login("x@example.com", "mauvais mot de passe", None)
    rows = await migrator_sql("SELECT email FROM lorakus.core_login_attempts ORDER BY email")
    assert rows == [("x@example.com",)]
