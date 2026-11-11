"""Montage des routes des modules : un module desactive pour l'utilisateur repond 404."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request, status

from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.core.modules.service import ModuleService

HEALTH_TIMEOUT_S = 2.0


def get_modules(request: Request) -> ModuleService:
    """Dependance : service des modules de l'application."""
    return cast(ModuleService, request.app.state.modules)


def module_guard(module_id: str) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependance ajoutee a toutes les routes d'un module : session valide ET module active."""

    async def guard(
        user: Annotated[CurrentUser, Depends(current_user)],
        modules: Annotated[ModuleService, Depends(get_modules)],
    ) -> CurrentUser:
        if not await modules.is_enabled(user.id, module_id):
            # 404 plutot que 403 : un module non active n'existe pas pour cet utilisateur.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Module indisponible.")
        return user

    return guard


def mount_module_routes(app: FastAPI, registry: ModuleRegistry) -> None:
    """Monte chaque routeur de module sous /api/v1/<id>, protege par module_guard."""
    for manifest in registry:
        if manifest.api_router is not None:
            app.include_router(
                manifest.api_router,
                prefix=f"/api/v1/{manifest.id}",
                tags=[manifest.name],
                dependencies=[Depends(module_guard(manifest.id))],
            )


async def module_health(registry: ModuleRegistry) -> dict[str, str]:
    """Etat de chaque module : ok, ko, timeout, error ou none (pas de verification)."""
    results: dict[str, str] = {}
    for manifest in registry:
        if manifest.health is None:
            results[manifest.id] = "none"
            continue
        try:
            healthy = await asyncio.wait_for(manifest.health(), HEALTH_TIMEOUT_S)
        except TimeoutError:
            results[manifest.id] = "timeout"
        except Exception:
            results[manifest.id] = "error"
        else:
            results[manifest.id] = "ok" if healthy else "ko"
    return results
