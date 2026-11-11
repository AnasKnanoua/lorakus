"""Isolation entre utilisateurs (RLS), verifiee avec le role de l'application.

Ces tests s'executent en lorakus_app : un superutilisateur ou le proprietaire des tables
contourneraient la RLS, et les tests passeraient a tort.
"""

import uuid

import pytest
from conftest import migrator_sql
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lorakus.core.identity.service import IdentityService
from lorakus.db.database import Database
from lorakus.settings import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

PASSWORD = "mot de passe de test assez long"


async def _two_users(identity: IdentityService) -> tuple[uuid.UUID, uuid.UUID]:
    first = await identity.create_owner("a@example.com", PASSWORD)
    # Le second utilisateur est cree par le proprietaire des tables (pas encore d'invitation).
    second = uuid.uuid4()
    await migrator_sql(
        "INSERT INTO lorakus.core_users (id, email, password_hash, role) "
        "VALUES (:id, 'b@example.com', 'x', 'user')",
        {"id": second},
    )
    return first, second


async def test_tests_run_as_application_role_without_bypass(database: Database) -> None:
    async with database.transaction() as session:
        row = (
            await session.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    assert tuple(row) == ("lorakus_app", False, False)


async def test_without_user_context_nothing_is_visible(
    database: Database, identity: IdentityService
) -> None:
    await _two_users(identity)
    async with database.transaction() as session:
        assert await session.scalar(text("SELECT count(*) FROM lorakus.core_users")) == 0
        assert await session.scalar(text("SELECT count(*) FROM lorakus.core_sessions")) == 0


async def test_user_sees_and_changes_only_own_rows(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)
    async with database.transaction(first) as session:
        ids = (await session.execute(text("SELECT id FROM lorakus.core_users"))).scalars().all()
        assert ids == [first]
        changed = await session.execute(
            text(
                "UPDATE lorakus.core_users SET password_hash = 'pirate' WHERE id = :id RETURNING id"
            ),
            {"id": second},
        )
        assert changed.all() == []
        deleted = await session.execute(
            text("DELETE FROM lorakus.core_users WHERE id = :id RETURNING id"), {"id": second}
        )
        assert deleted.all() == []
    rows = await migrator_sql(
        "SELECT password_hash FROM lorakus.core_users WHERE id = :id", {"id": second}
    )
    assert rows == [("x",)]


async def test_cannot_write_rows_for_another_user(
    database: Database, identity: IdentityService
) -> None:
    first, second = await _two_users(identity)
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with database.transaction(first) as session:
            await session.execute(
                text(
                    "INSERT INTO lorakus.core_sessions "
                    "(id, user_id, token_hash, last_seen_at, expires_at) "
                    "VALUES (:id, :owner, :hash, now(), now() + interval '1 day')"
                ),
                {"id": uuid.uuid4(), "owner": second, "hash": b"x" * 32},
            )


async def test_application_cannot_change_role_or_email(
    database: Database, identity: IdentityService
) -> None:
    first, _ = await _two_users(identity)
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with database.transaction(first) as session:
            await session.execute(
                text("UPDATE lorakus.core_users SET role = 'owner' WHERE id = :id"), {"id": first}
            )


async def test_login_attempts_are_not_directly_accessible(database: Database) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with database.transaction() as session:
            await session.execute(text("SELECT * FROM lorakus.core_login_attempts"))


async def test_user_context_does_not_leak_to_the_next_transaction(
    identity: IdentityService,
) -> None:
    """Pool d'UNE connexion : la transaction suivante reutilise la meme, sans l'identite."""
    first, _ = await _two_users(identity)
    engine = create_async_engine(get_settings().app_database_url(), pool_size=1, max_overflow=0)
    single = Database(engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with single.transaction(first) as session:
            pid_with_user = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT lorakus.current_user_id()")) == first
        async with single.transaction() as session:
            assert await session.scalar(text("SELECT pg_backend_pid()")) == pid_with_user
            assert await session.scalar(text("SELECT lorakus.current_user_id()")) is None
            assert await session.scalar(text("SELECT count(*) FROM lorakus.core_users")) == 0
    finally:
        await single.close()


async def test_every_table_has_forced_row_level_security(database: Database) -> None:
    async with database.transaction() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relnamespace = 'lorakus'::regnamespace AND relkind = 'r' "
                    "AND relname <> 'alembic_version' ORDER BY relname"
                )
            )
        ).all()
    assert rows, "aucune table trouvee"
    unprotected = [name for name, enabled, forced in rows if not (enabled and forced)]
    assert unprotected == []


async def test_auth_functions_are_narrow_security_definers(database: Database) -> None:
    async with database.transaction() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT proname, prosecdef, pg_get_userbyid(proowner), proconfig, "
                    "has_function_privilege('public', oid, 'EXECUTE') FROM pg_proc "
                    "WHERE pronamespace = 'lorakus'::regnamespace "
                    "AND (proname LIKE 'auth\\_%' OR proname LIKE 'audit\\_%') "
                    "ORDER BY proname"
                )
            )
        ).all()
    assert [r[0] for r in rows] == [
        "audit_record",
        "auth_failures",
        "auth_find_api_key",
        "auth_find_login",
        "auth_find_session",
        "auth_owner_exists",
        "auth_record_attempt",
    ]
    for name, definer, owner, config, public_can_execute in rows:
        assert definer, name
        assert owner == "lorakus_migrator", name
        assert config == ["search_path=lorakus, pg_temp"], name
        assert not public_can_execute, name


def test_no_session_level_set_in_code() -> None:
    """Garde-fou : l'identite n'est jamais posee par un SET de session dans le code."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "lorakus"
    pattern = re.compile(r"\bSET\s+(SESSION\s+)?lorakus\.|set_config\([^)]*,\s*false\)", re.I)
    offenders = [
        str(path) for path in root.rglob("*.py") if pattern.search(path.read_text("utf-8"))
    ]
    assert offenders == []
