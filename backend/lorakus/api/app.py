"""Construction de l'application FastAPI."""

from importlib.metadata import version

from fastapi import FastAPI

from lorakus.api.routes import health
from lorakus.settings import get_settings


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
        # Documentation interactive desactivee en production (surface d'attaque).
        docs_url=None if is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/api/openapi.json",
    )
    app.include_router(health.router, prefix="/api")
    return app
