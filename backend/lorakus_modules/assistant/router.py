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
from lorakus.api.ai import get_ai
from lorakus.api.auth import client_ip, current_user
from lorakus.api.memory import get_background, get_memory
from lorakus.api.tools import get_tools
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
) -> AssistantService:
    settings = get_settings()
    return AssistantService(
        cast(Database, request.app.state.database),
        ai,
        memory=memory,
        background=background,
        memory_delay_s=settings.memory_proposal_delay_seconds,
        tools=tools,
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
