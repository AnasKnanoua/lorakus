"""Environnement Alembic : applique les migrations avec le role lorakus_migrator."""

import asyncio
import importlib
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from lorakus.ai import models as _ai_models  # noqa: F401 (tables enregistrees)
from lorakus.core.agents import models as _agent_models  # noqa: F401
from lorakus.core.events import models as _event_models  # noqa: F401
from lorakus.core.identity import models as _identity_models  # noqa: F401
from lorakus.core.memory import models as _memory_models  # noqa: F401
from lorakus.core.modules import models as _module_models  # noqa: F401
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.ratelimit import models as _rate_limit_models  # noqa: F401
from lorakus.core.tools import models as _tool_models  # noqa: F401
from lorakus.db.base import SCHEMA, Base
from lorakus.settings import get_settings

# Tables des modules installes : leurs modeles sont importes pour que alembic check les
# compare aussi a la base.
_modules = list(ModuleRegistry.from_entry_points())
for _manifest in _modules:
    if _manifest.models:
        importlib.import_module(_manifest.models)

# Garde-fou : Alembic ignore en silence un dossier de migrations absent. Sans ce controle,
# une image mal construite declarerait la base a jour sans les tables d'un module, et l'API
# demarrerait quand meme (erreurs 500 ensuite). Ici, la migration echoue, donc le deploiement.
_known_branches = {
    label for revision in context.script.walk_revisions() for label in revision.branch_labels
}
_missing = sorted(
    m.migrations for m in _modules if m.migrations and m.migrations not in _known_branches
)
if _missing:
    raise RuntimeError(
        f"migrations introuvables pour : {', '.join(_missing)} "
        "(verifier version_locations dans alembic.ini et la copie des migrations dans l'image)"
    )

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
