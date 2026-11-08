"""Construction de l'application FastAPI."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from lorakus.api.routes import health
from lorakus.db.database import Database
from lorakus.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Ouvre les ressources au demarrage et les ferme a l'arret."""
    database = Database.connect(get_settings())
    app.state.database = database
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    """Fabrique et configure une application neuve.

    Une fonction plutot qu'une variable globale : chaque test peut creer sa
    propre application isolee, et la configuration est lue au bon moment.
    """
    settings = get_settings()
    is_production = settings.environment == "production"

    app = FastAPI(
        title=settings.app_display_name,
        version=version("lorakus"),
        lifespan=lifespan,
        # Documentation interactive desactivee en production (surface d'attaque).
        docs_url=None if is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/api/openapi.json",
    )
    app.include_router(health.router, prefix="/api")
    return app
