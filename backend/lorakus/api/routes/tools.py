"""Outils et specialistes : /api/v1/tools/... et /api/v1/agents/..."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from lorakus.api.auth import REAUTH_REQUIRED, client_ip, current_user, get_identity
from lorakus.core.agents.contract import SpecialistReport
from lorakus.core.agents.service import AgentError, AgentService
from lorakus.core.identity.service import CurrentUser, IdentityService
from lorakus.core.tools.runtime import ToolError, ToolResult, ToolRuntime

router = APIRouter(prefix="/v1", tags=["outils et specialistes"])
User = Annotated[CurrentUser, Depends(current_user)]
Identity = Annotated[IdentityService, Depends(get_identity)]


def get_tools(request: Request) -> ToolRuntime:
    return cast(ToolRuntime, request.app.state.tools)


def get_agents(request: Request) -> AgentService:
    return cast(AgentService, request.app.state.agents)


Tools = Annotated[ToolRuntime, Depends(get_tools)]
Agents = Annotated[AgentService, Depends(get_agents)]


class ToolInfo(BaseModel):
    name: str
    description: str
    risk: str
    input_schema: dict[str, Any]


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


class ToolCallResponse(BaseModel):
    tool: str
    risk: str
    result: dict[str, Any] | None = None
    confirmation_id: UUID | None = None


class SpecialistInfo(BaseModel):
    name: str
    display_name: str
    intents: list[str]
    limits: str


class AskRequest(BaseModel):
    intent: str
    params: dict[str, Any] = {}


class AskResponse(BaseModel):
    specialist: str
    duration_ms: int
    report: SpecialistReport


def _response(result: ToolResult) -> ToolCallResponse:
    return ToolCallResponse(
        tool=result.tool,
        risk=result.risk,
        result=result.result,
        confirmation_id=result.confirmation_id,
    )


@router.get("/tools")
async def list_tools(tools: Tools, user: User) -> list[ToolInfo]:
    """Outils des modules actives."""
    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            risk=t.risk,
            input_schema=t.input_model.model_json_schema(),
        )
        for t in await tools.available(user.id)
    ]


@router.post("/tools/{name}")
async def call_tool(
    name: str, body: ToolCallRequest, request: Request, response: Response, tools: Tools, user: User
) -> ToolCallResponse:
    """Outil read : execute (200). Outil write ou sensitive : confirmation requise (202)."""
    try:
        result = await tools.call(user.id, name, body.arguments, client_ip(request))
    except ToolError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    if result.confirmation_id is not None:
        response.status_code = status.HTTP_202_ACCEPTED
    return _response(result)


@router.post("/tools/confirmations/{confirmation_id}")
async def confirm_tool(
    confirmation_id: UUID, request: Request, tools: Tools, identity: Identity, user: User
) -> ToolCallResponse:
    """Execute une action en attente. Une action sensible exige une re-authentification recente."""
    try:
        risk = await tools.risk_of_confirmation(user.id, confirmation_id)
        if risk == "sensitive" and not identity.recently_authenticated(user):
            raise REAUTH_REQUIRED
        return _response(await tools.confirm(user.id, confirmation_id, client_ip(request)))
    except ToolError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None


@router.get("/agents")
async def list_specialists(agents: Agents, user: User) -> list[SpecialistInfo]:
    """Specialistes des modules actives."""
    return [
        SpecialistInfo(
            name=p.name, display_name=p.display_name, intents=list(p.intents), limits=p.limits
        )
        for p in await agents.available(user.id)
    ]


@router.post("/agents/{name}/ask")
async def ask_specialist(name: str, body: AskRequest, agents: Agents, user: User) -> AskResponse:
    """Pose une question typee a un specialiste (API interne ; le Majordome arrive en P3)."""
    try:
        answer = await agents.ask(user.id, name, body.intent, body.params)
    except AgentError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    return AskResponse(
        specialist=answer.specialist, duration_ms=answer.duration_ms, report=answer.report
    )
