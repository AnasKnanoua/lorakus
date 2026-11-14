"""Routes du module Assistant, montees sous /api/v1/assistant.

Le Core ajoute lui-meme la verification de session et d'activation du module. La reponse
a un message arrive en Server-Sent Events (text/event-stream) :

    event: delta   data: {"text": "..."}          (zero, une ou plusieurs fois)
    event: tool    data: {"tool": "...", "label": "...", "ok": true}   (outil read, PR 38)
    event: card    data: {"confirmation_id": "...", "tool": "...", "risk": "write|sensitive",
                          "summary": "...", "expires_at": "...", "status": "pending"}
    event: done    data: {"message_id": "...", "status": "ok|interrupted|fallback",
                          "budget_warning": false}

Une carte se confirme par POST /api/v1/tools/confirmations/{id} (preuve d'identite recente
pour une action sensitive) et se refuse par .../cancel : routes du Core, jamais du modele.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from lorakus.ai.router import ModelRouter
from lorakus.api.agents import get_intent_router, get_orchestrator
from lorakus.api.ai import get_ai
from lorakus.api.auth import client_ip, current_user
from lorakus.api.memory import get_background, get_memory
from lorakus.api.tools import get_tools
from lorakus.core.agents.orchestrator import Orchestrator
from lorakus.core.agents.routing import IntentRouter
from lorakus.core.background import DebouncedTasks
from lorakus.core.identity.service import CurrentUser
from lorakus.core.memory.service import MemoryService
from lorakus.core.modules.service import ModuleService
from lorakus.core.tools.runtime import ToolRuntime
from lorakus.db.database import Database
from lorakus.settings import get_settings
from lorakus_modules.assistant.config import AssistantConfig
from lorakus_modules.assistant.service import (
    MAX_MESSAGE_CHARS,
    Activity,
    AssistantService,
    Card,
    ConversationNotFoundError,
    Delta,
    ReplyEvent,
)

MODULE_ID: Final = "assistant"

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Conversation introuvable.")


def _service(
    request: Request,
    ai: Annotated[ModelRouter, Depends(get_ai)],
    memory: Annotated[MemoryService, Depends(get_memory)],
    background: Annotated[DebouncedTasks, Depends(get_background)],
    tools: Annotated[ToolRuntime, Depends(get_tools)],
    orchestrator: Annotated[Orchestrator, Depends(get_orchestrator)],
    intent_router: Annotated[IntentRouter, Depends(get_intent_router)],
) -> AssistantService:
    settings = get_settings()
    return AssistantService(
        cast(Database, request.app.state.database),
        ai,
        memory=memory,
        background=background,
        memory_delay_s=settings.memory_proposal_delay_seconds,
        tools=tools,
        orchestrator=orchestrator,
        intent_router=intent_router,
    )


Service = Annotated[AssistantService, Depends(_service)]


async def _config(request: Request, user: CurrentUser) -> AssistantConfig:
    modules = cast(ModuleService, request.app.state.modules)
    return AssistantConfig.model_validate(await modules.config(user.id, MODULE_ID))


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ActionOut(BaseModel):
    """Outil d'une reponse : indication (activity) ou carte de confirmation (card)."""

    kind: Literal["activity", "card"]
    tool: str
    label: str | None = None
    ok: bool | None = None
    confirmation_id: uuid.UUID | None = None
    risk: str | None = None
    summary: str | None = None
    expires_at: datetime | None = None
    status: Literal["pending", "confirmed", "cancelled", "expired"] | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    model: str | None
    cost_usd: Decimal | None
    created_at: datetime
    actions: list[ActionOut] = []


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


@router.get("/conversations")
async def list_conversations(user: User, service: Service) -> list[ConversationOut]:
    rows = await service.list_conversations(user.id)
    return [ConversationOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(user: User, service: Service) -> ConversationOut:
    conversation = await service.create_conversation(user.id)
    return ConversationOut.model_validate(conversation, from_attributes=True)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, user: User, service: Service
) -> ConversationDetail:
    try:
        conversation, messages = await service.conversation(user.id, conversation_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None
    statuses = await service.card_statuses(user.id, messages)

    def actions(stored: list[dict[str, Any]]) -> list[ActionOut]:
        out: list[ActionOut] = []
        for action in stored:
            item = ActionOut.model_validate(action)
            if item.kind == "card" and item.confirmation_id is not None:
                # Ligne disparue (compte efface...) : la carte ne peut plus etre confirmee.
                item.status = statuses.get(item.confirmation_id, "expired")
            out.append(item)
        return out

    return ConversationDetail(
        **ConversationOut.model_validate(conversation, from_attributes=True).model_dump(),
        messages=[
            MessageOut.model_validate(m, from_attributes=True).model_copy(
                update={"actions": actions(m.actions)}
            )
            for m in messages
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, user: User, service: Service) -> Response:
    try:
        await service.delete_conversation(user.id, conversation_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TraceFact(BaseModel):
    id: uuid.UUID
    content: str
    category: str


class TraceTool(BaseModel):
    tool: str
    kind: Literal["activity", "card"]
    text: str
    status: str | None = None


class TraceSpecialist(BaseModel):
    specialist: str
    display_name: str
    intent: str
    status: str
    duration_ms: int
    cached: bool
    skipped: str | None = None
    data_classes: list[str]


class TraceRouting(BaseModel):
    tier: str
    best: str | None = None
    score: float | None = None
    runner_up: float | None = None
    reason: str


class TraceOut(BaseModel):
    """« Pourquoi m'as-tu dit ca ? » (PR 39) : ce qui a servi a ecrire une reponse."""

    message_id: uuid.UUID
    prompt_version: str | None
    model: str | None
    model_calls: int
    cost_usd: Decimal | None
    data_classes_sent: list[str]
    memory_facts: list[TraceFact]
    # Souvenirs fournis a l'epoque mais supprimes depuis : seulement leur nombre.
    memory_facts_removed: int
    tools: list[TraceTool]
    routing: TraceRouting | None
    specialists: list[TraceSpecialist]
    # Identifiant de la trace OpenTelemetry (PR 40), a chercher dans Grafana (Tempo) ;
    # None si la telemetrie est desactivee ou pour une reponse anterieure.
    otel_trace_id: str | None = None


@router.get("/conversations/{conversation_id}/messages/{message_id}/trace")
async def reply_trace(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user: User,
    service: Service,
    memory: Annotated[MemoryService, Depends(get_memory)],
) -> TraceOut:
    """Explication d'une reponse. 404 si elle n'existe pas, n'est pas a l'utilisateur, ou est
    anterieure aux traces."""
    try:
        message = await service.reply(user.id, conversation_id, message_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None
    trace = cast(dict[str, Any] | None, message.trace)
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune explication pour cette réponse.")
    given = [uuid.UUID(i) for i in trace.get("memory_fact_ids", [])]
    current = {f.id: f for f in await memory.list_facts(user.id) if f.status == "verified"}
    facts = [
        TraceFact(id=i, content=current[i].content, category=current[i].category)
        for i in given
        if i in current
    ]
    statuses = await service.card_statuses(user.id, [message])
    tools: list[TraceTool] = []
    for action in cast(list[dict[str, Any]], message.actions):
        if action.get("kind") == "card":
            card_id = uuid.UUID(str(action["confirmation_id"]))
            tools.append(
                TraceTool(
                    tool=str(action["tool"]),
                    kind="card",
                    text=str(action["summary"]),
                    status=statuses.get(card_id, "expired"),
                )
            )
        else:
            tools.append(
                TraceTool(
                    tool=str(action["tool"]),
                    kind="activity",
                    text=str(action.get("label", "")),
                    status="ok" if action.get("ok", True) else "error",
                )
            )
    routing = trace.get("routing")
    return TraceOut(
        message_id=message.id,
        prompt_version=trace.get("prompt_version"),
        model=trace.get("model"),
        model_calls=int(trace.get("model_calls") or 0),
        cost_usd=Decimal(trace["cost_usd"]) if trace.get("cost_usd") else None,
        data_classes_sent=list(trace.get("data_classes_sent", [])),
        memory_facts=facts,
        memory_facts_removed=len(given) - len(facts),
        tools=tools,
        routing=TraceRouting.model_validate(routing) if routing else None,
        specialists=[TraceSpecialist.model_validate(s) for s in trace.get("specialists", [])],
        otel_trace_id=trace.get("otel_trace_id"),
    )


def _sse(event: ReplyEvent) -> str:
    data: dict[str, Any]
    if isinstance(event, Delta):
        name, data = "delta", {"text": event.text}
    elif isinstance(event, Activity):
        name, data = "tool", {"tool": event.tool, "label": event.label, "ok": event.ok}
    elif isinstance(event, Card):
        name, data = (
            "card",
            {
                "confirmation_id": str(event.confirmation_id),
                "tool": event.tool,
                "risk": event.risk,
                "summary": event.summary,
                "expires_at": event.expires_at.isoformat(),
                "status": "pending",
            },
        )
    else:
        name, data = (
            "done",
            {
                "message_id": str(event.message_id),
                "status": event.status,
                "budget_warning": event.budget_warning,
            },
        )
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Reponse en flux : evenements delta, puis un evenement done.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        404: {"description": "Conversation introuvable."},
    },
)
async def send_message(
    conversation_id: uuid.UUID, body: MessageIn, request: Request, user: User, service: Service
) -> StreamingResponse:
    config = await _config(request, user)
    try:
        turn = await service.start_turn(
            user.id, conversation_id, body.content, config, ip=client_ip(request)
        )
    except ConversationNotFoundError:
        raise NOT_FOUND from None

    async def events() -> AsyncGenerator[str]:
        reply = service.play(turn)
        try:
            async for event in reply:
                yield _sse(event)
        finally:
            await reply.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-store : rien de la conversation dans un cache ; no-transform : pas de
        # compression intermediaire qui retiendrait le flux.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
