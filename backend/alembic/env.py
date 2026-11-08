"""Environnement Alembic : applique les migrations avec le role lorakus_migrator."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from lorakus.db.base import SCHEMA, Base
from lorakus.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Limite la comparaison automatique au seul schema de Lorakus."""
    if type_ == "schema":
        return name == SCHEMA
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        get_settings().migrator_database_url(),
        poolclass=pool.NullPool,
        connect_args={"application_name": "lorakus-migrate", "options": "-c lock_timeout=5000"},
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Mode hors ligne non supporte : les migrations s'appliquent sur une base.")

asyncio.run(run_async_migrations())
