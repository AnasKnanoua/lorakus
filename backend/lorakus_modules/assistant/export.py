"""Export des donnees du module Assistant (PR 41) : conversations et messages.

Appele par le Core (DataExportService) pour « Mes donnees », que le module soit actif ou non.
Chaque message garde ses actions (indications d'outils, cartes) et sa trace « Pourquoi ? ».
"""

import uuid
from typing import Any

from sqlalchemy import select

from lorakus.core.data.export import DataExportContext
from lorakus_modules.assistant.models import AssistantConversation, AssistantMessage


async def export_assistant(context: DataExportContext) -> dict[str, Any]:
    """Toutes les conversations de l'utilisateur, les plus anciennes d'abord."""
    async with context.open_transaction() as session:
        conversations = list(
            await session.scalars(
                select(AssistantConversation).order_by(
                    AssistantConversation.created_at, AssistantConversation.id
                )
            )
        )
        messages = list(
            await session.scalars(
                select(AssistantMessage).order_by(AssistantMessage.created_at, AssistantMessage.id)
            )
        )
    by_conversation: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for m in messages:
        by_conversation.setdefault(m.conversation_id, []).append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "status": m.status,
                "model": m.model,
                "prompt_version": m.prompt_version,
                "cost_usd": m.cost_usd,
                "created_at": m.created_at,
                "actions": m.actions,
                "trace": m.trace,
            }
        )
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "messages": by_conversation.get(c.id, []),
            }
            for c in conversations
        ]
    }
