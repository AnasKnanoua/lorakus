"""Construction de l'application FastAPI."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from lorakus.ai.catalog import Catalog
from lorakus.ai.providers import build_embedder, build_providers
from lorakus.ai.router import ModelRouter
from lorakus.ai.usage import UsageStore
from lorakus.api.auth import RequestLimits
from lorakus.api.modules import mount_module_routes
from lorakus.api.origin import OriginCheckMiddleware
from lorakus.api.routes import auth, health, memory, modules, tools
from lorakus.core.agents.service import AgentService
from lorakus.core.background import DebouncedTasks
from lorakus.core.identity.service import IdentityService
from lorakus.core.memory.service import MemoryService
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.modules.service import ModuleService
from lorakus.core.ratelimit.service import AICallQuota, Limit, RateLimiter
from lorakus.core.tools.runtime import ToolRuntime
from lorakus.db.database import Database
from lorakus.observability.logging import configure_logging
from lorakus.observability.metrics import start_metrics_server
from lorakus.observability.request_context import RequestContextMiddleware
from lorakus.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Ouvre les ressources au demarrage et les ferme a l'arret."""
    settings = get_settings()
    if settings.metrics_port is not None:
        start_metrics_server(settings.metrics_port)
    database = Database.connect(settings)
    app.state.database = database
    app.state.identity = IdentityService(database, settings)
    app.state.modules = ModuleService(database, app.state.registry)
    app.state.tools = ToolRuntime(database, app.state.modules)
    app.state.agents = AgentService(database, app.state.modules)
    app.state.rate_limiter = RateLimiter(database)
    app.state.request_limits = RequestLimits(
        all_requests=Limit("api.requests", 60, settings.api_requests_per_minute),
        writes=Limit("api.writes", 60, settings.api_writes_per_minute),
    )
    app.state.ai = ModelRouter(
        app.state.ai_catalog,
        build_providers(settings),
        UsageStore(database),
        monthly_budget_usd=settings.ai_monthly_budget_usd,
        kill_switch=settings.ai_kill_switch,
        quota=AICallQuota(
            app.state.rate_limiter,
            per_minute=settings.ai_calls_per_minute,
            per_day=settings.ai_calls_per_day,
        ),
        max_concurrent_per_user=settings.ai_concurrent_calls,
    )
    # Modele d'embeddings local, charge une fois (quelques secondes, hors boucle d'evenements).
    # Absent en staging ou en production : EmbeddingError, l'API ne demarre pas.
    app.state.embedder = await asyncio.to_thread(build_embedder, settings)
    app.state.memory = MemoryService(database, app.state.ai, app.state.embedder)
    app.state.background = DebouncedTasks()
    try:
        yield
    finally:
        await app.state.background.close()
        await database.close()


def create_app(registry: ModuleRegistry | None = None) -> FastAPI:
    """Fabrique et configure une application neuve.

    registry : modules a monter ; par defaut, ceux declares par entry point. Un ensemble
    incoherent leve ModuleRegistryError : l'application ne demarre pas.

    Une fonction plutot qu'une variable globale : chaque test peut creer sa
    propre application isolee, et la configuration est lue au bon moment.
    """
    settings = get_settings()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    is_production = settings.environment == "production"
    if settings.environment in ("staging", "production") and not settings.public_origin:
        # Sans origine connue, toute ecriture depuis un navigateur serait refusee.
        raise ValueError(f"LORAKUS_PUBLIC_ORIGIN manquante en {settings.environment}")

    app = FastAPI(
        title=settings.app_display_name,
        version=version("lorakus"),
        lifespan=lifespan,
        # Documentation interactive desactivee en production (surface d'attaque).
        docs_url=None if is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/api/openapi.json",
    )
    # Ordre d'execution : RequestContext (identifiant, journal, metriques) puis l'origine.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins())
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(modules.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.state.registry = registry if registry is not None else ModuleRegistry.from_entry_points()
    # Routage et prix verifies ici : une configuration IA invalide empeche le demarrage.
    app.state.ai_catalog = Catalog.load()
    mount_module_routes(app, app.state.registry)
    return app
