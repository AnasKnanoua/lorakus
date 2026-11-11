"""Acces a PostgreSQL : moteur, pool de connexions et verification."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self, cast

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lorakus.settings import Settings

# Garde-fous appliques par le serveur a chaque connexion de l'application :
# une requete, une attente de verrou ou une transaction oubliee ne peuvent
# pas bloquer la base indefiniment.
_SERVER_OPTIONS = (
    "-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=10000"
)


@dataclass(frozen=True)
class Database:
    """Point d'acces unique a la base pour l'application."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def connect(cls, settings: Settings) -> Self:
        """Prepare le pool de connexions (aucune connexion n'est ouverte ici)."""
        engine = create_async_engine(
            settings.app_database_url(),
            pool_size=5,
            max_overflow=5,
            pool_timeout=5,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "application_name": "lorakus-api",
                "options": _SERVER_OPTIONS,
                "connect_timeout": 3,
            },
        )
        return cls(engine=engine, sessions=async_sessionmaker(engine, expire_on_commit=False))

    @asynccontextmanager
    async def transaction(self, user_id: uuid.UUID | None = None) -> AsyncGenerator[AsyncSession]:
        """Ouvre une transaction ; avec user_id, la RLS ne laisse voir que ses donnees.

        Sans user_id, aucune ligne protegee par la RLS n'est visible : seules les fonctions
        d'authentification (SECURITY DEFINER) peuvent alors lire ce qu'il faut.
        """
        async with self.sessions() as session, session.begin():
            if user_id is not None:
                await bind_user(session, user_id)
            yield session

    async def ping(self) -> None:
        """Verifie que la base repond (requete fixe, sans aucune donnee externe)."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Ferme proprement toutes les connexions du pool."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """Dependance FastAPI : retourne la base attachee a l'application."""
    return cast(Database, request.app.state.database)


async def bind_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Positionne l'utilisateur courant pour la RLS, pour la transaction en cours SEULEMENT.

    set_config(..., true) equivaut a SET LOCAL : la valeur disparait a la fin de la
    transaction. Un SET de session resterait sur la connexion, que le pool redonnerait
    ensuite a une autre requete, avec l'identite du client precedent.
    """
    if not session.in_transaction():
        raise RuntimeError("bind_user exige une transaction ouverte")
    await session.execute(
        text("SELECT set_config('lorakus.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
