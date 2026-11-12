"""Routes du module Assistant, montees sous /api/v1/assistant.

Le Core ajoute lui-meme la verification de session et d'activation du module. La reponse
a un message arrive en Server-Sent Events (text/event-stream) :

    event: delta   data: {"text": "..."}          (zero, une ou plusieurs fois)
    event: done    data: {"message_id": "...", "status": "ok|interrupted|fallback",
                          "budget_warning": false}
"""

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Final, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from lorakus.ai.router import ModelRouter
from lorakus.api.ai import get_ai
from lorakus.api.auth import current_user
from lorakus.core.identity.service import CurrentUser
from lorakus.core.modules.service import ModuleService
from lorakus.db.database import Database
from lorakus_modules.assistant.config import AssistantConfig
from lorakus_modules.assistant.service import (
    MAX_MESSAGE_CHARS,
    AssistantService,
    ConversationNotFoundError,
    Delta,
    ReplyEvent,
)

MODULE_ID: Final = "assistant"

router = APIRouter()
User = Annotated[CurrentUser, Depends(current_user)]
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Conversation introuvable.")


def _service(request: Request, ai: Annotated[ModelRouter, Depends(get_ai)]) -> AssistantService:
    return AssistantService(cast(Database, request.app.state.database), ai)


Service = Annotated[AssistantService, Depends(_service)]


async def _config(request: Request, user: CurrentUser) -> AssistantConfig:
    modules = cast(ModuleService, request.app.state.modules)
    return AssistantConfig.model_validate(await modules.config(user.id, MODULE_ID))


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    model: str | None
    cost_usd: Decimal | None
    created_at: datetime


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
    return ConversationDetail(
        **ConversationOut.model_validate(conversation, from_attributes=True).model_dump(),
        messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, user: User, service: Service) -> Response:
    try:
        await service.delete_conversation(user.id, conversation_id)
    except ConversationNotFoundError:
        raise NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sse(event: ReplyEvent) -> str:
    if isinstance(event, Delta):
        name, data = "delta", {"text": event.text}
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
        turn = await service.start_turn(user.id, conversation_id, body.content, config)
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
