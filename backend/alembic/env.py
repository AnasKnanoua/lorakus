"""Environnement Alembic : applique les migrations avec le role lorakus_migrator."""

import asyncio
import importlib
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from lorakus.core.agents import models as _agent_models  # noqa: F401 (tables enregistrees)
from lorakus.core.events import models as _event_models  # noqa: F401
from lorakus.core.identity import models as _identity_models  # noqa: F401
from lorakus.core.modules import models as _module_models  # noqa: F401
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.tools import models as _tool_models  # noqa: F401
from lorakus.db.base import SCHEMA, Base
from lorakus.settings import get_settings

# Tables des modules installes : leurs modeles sont importes pour que alembic check les
# compare aussi a la base.
for _manifest in ModuleRegistry.from_entry_points():
    if _manifest.models:
        importlib.import_module(_manifest.models)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Limite la comparaison automatique au seul schema de Lorakus."""
    if type_ == "schema":
        return name == SCHEMA
    # Tables de la file de jobs : gerees par Procrastinate (migration 0005), pas par nos modeles.
    return not (type_ == "table" and name is not None and name.startswith("procrastinate_"))


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
        connect_args={
            "application_name": "lorakus-migrate",
            # search_path neutre : le schema lorakus n'est plus le schema "par defaut", et
            # la comparaison des modeles (alembic check) le traite comme un schema nomme,
            # a l'identique des modeles. Toutes les migrations qualifient leurs objets.
            "options": "-c lock_timeout=5000 -c search_path=pg_catalog",
        },
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Mode hors ligne non supporte : les migrations s'appliquent sur une base.")

asyncio.run(run_async_migrations())
