"""Routes de gestion des modules : /api/v1/modules/..."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from lorakus.api.auth import client_ip, current_user
from lorakus.api.modules import get_modules, module_health
from lorakus.core.identity.service import CurrentUser
from lorakus.core.modules.service import (
    ModuleConfigError,
    ModuleService,
    ModuleState,
    ModuleStateError,
)

router = APIRouter(prefix="/v1/modules", tags=["modules"])

Modules = Annotated[ModuleService, Depends(get_modules)]
User = Annotated[CurrentUser, Depends(current_user)]


class FrontendResponse(BaseModel):
    route: str
    label: str
    icon: str


class ModuleResponse(BaseModel):
    id: str
    name: str
    version: str
    description: str
    enabled: bool
    config: dict[str, Any]
    config_schema: dict[str, Any] | None
    permissions: list[str]
    depends_on: list[str]
    frontend: FrontendResponse | None


class ModuleUpdateRequest(BaseModel):
    enabled: bool
    config: dict[str, Any] | None = None


def _response(state: ModuleState) -> ModuleResponse:
    manifest = state.manifest
    return ModuleResponse(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        enabled=state.enabled,
        config=state.config,
        config_schema=(
            manifest.config_schema.model_json_schema() if manifest.config_schema else None
        ),
        permissions=list(manifest.permissions),
        depends_on=list(manifest.depends_on),
        frontend=(
            FrontendResponse(**manifest.frontend.model_dump()) if manifest.frontend else None
        ),
    )


@router.get("")
async def list_modules(modules: Modules, user: User) -> list[ModuleResponse]:
    """Modules installes et leur etat pour l'utilisateur."""
    return [_response(state) for state in await modules.states(user.id)]


@router.put("/{module_id}")
async def update_module(
    module_id: str, body: ModuleUpdateRequest, request: Request, modules: Modules, user: User
) -> ModuleResponse:
    """Active, desactive ou configure un module (configuration validee par son schema)."""
    if modules.registry.get(module_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module inconnu.")
    try:
        state = await modules.set_state(
            user.id, module_id, body.enabled, body.config, client_ip(request)
        )
    except ModuleConfigError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except ModuleStateError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    return _response(state)


@router.get("/health")
async def modules_health(modules: Modules, user: User) -> dict[str, str]:
    """Etat de sante de chaque module (proprietaire seulement)."""
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Reserve au proprietaire.")
    return await module_health(modules.registry)
