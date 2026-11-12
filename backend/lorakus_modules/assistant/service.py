"""Conversations de l'assistant : un tour = message de l'utilisateur -> reponse en flux.

Tout passe par le ModelRouter (jamais un SDK). Quand l'IA est indisponible ou refuse, la
reponse est un gabarit fixe (scenario 8 du MVP) : l'utilisateur sait toujours ce qui se
passe, et son message est enregistre dans tous les cas.

Le prompt envoye est borne : seuls les derniers messages tiennent dans HISTORY_TOKENS, pour
que le cout d'un message reste petit meme dans une longue conversation.
"""

import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal, cast
from zoneinfo import ZoneInfo

import anyio
import structlog
from prometheus_client import Counter
from sqlalchemy import delete, func, insert, select, update

from lorakus.ai.port import ChatMessage, ChatRequest, TextDelta, estimate_tokens
from lorakus.ai.router import (
    AIInterruptedError,
    AIRefusedError,
    AIUnavailableError,
    ChatResult,
    ModelRouter,
)
from lorakus.db.database import Database
from lorakus_modules.assistant.config import AssistantConfig
from lorakus_modules.assistant.models import AssistantConversation, AssistantMessage
from lorakus_modules.assistant.prompts import PROMPT_VERSION, system_prompt

log = structlog.get_logger("lorakus.assistant")

TASK: Final = "chat"
HISTORY_TOKENS: Final = 6000  # environ 0,0006 $ d'entree par message avec Haiku 5.5
MAX_MESSAGE_CHARS: Final = 8000
TITLE_CHARS: Final = 60
DEFAULT_TITLE: Final = "Nouvelle conversation"

MessageStatus = Literal["ok", "interrupted", "fallback"]
Role = Literal["user", "assistant"]

REPLIES: Final = Counter(
    "lorakus_assistant_replies_total",
    "Reponses de l'assistant (status : ok, interrupted, fallback)",
    ["status", "reason"],
)

# Gabarits : affiches quand le modele ne peut pas repondre. Jamais de detail technique.
FALLBACKS: Final[dict[str, str]] = {
    "budget": (
        "J'ai atteint le budget d'IA prévu pour ce mois : je ne peux plus utiliser mon modèle "
        "de langage avant le 1er du mois prochain. Votre message est bien enregistré."
    ),
    "unavailable": (
        "Mon modèle de langage est indisponible pour le moment. Réessayez dans quelques "
        "minutes ; votre message est bien enregistré."
    ),
    "too_long": (
        "Ce message est trop long pour que je le traite en une fois. Pouvez-vous le raccourcir "
        "ou le découper ?"
    ),
    "refused": "Je ne peux pas envoyer ces données à un modèle externe.",
    "error": "Une erreur interne m'empêche de répondre. Elle a été signalée ; réessayez plus tard.",
}


class ConversationNotFoundError(Exception):
    """Conversation absente ou appartenant a un autre utilisateur (la RLS les confond)."""


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Done:
    message_id: uuid.UUID
    status: MessageStatus
    budget_warning: bool


ReplyEvent = Delta | Done


@dataclass(frozen=True)
class StoredMessage:
    role: Role
    content: str
    status: MessageStatus


@dataclass(frozen=True)
class Turn:
    """Tour pret a etre joue : tout ce qui peut echouer avec une 404 est deja verifie."""

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    request: ChatRequest


def title_from(text: str) -> str:
    """Titre deterministe : debut du premier message, sur une ligne (aucun appel IA)."""
    line = " ".join(text.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def fit_history(messages: Sequence[StoredMessage], budget_tokens: int) -> list[ChatMessage]:
    """Derniers messages qui tiennent dans le budget, prets pour le modele.

    - Les gabarits de repli sont ecartes : ce ne sont pas des reponses du modele.
    - Deux messages consecutifs du meme role sont fusionnes (le modele attend une alternance).
    - Le dernier message est toujours garde ; l'historique commence par un message utilisateur.
    """
    merged: list[ChatMessage] = []
    for message in messages:
        if message.status == "fallback" or not message.content.strip():
            continue
        if merged and merged[-1].role == message.role:
            previous = merged.pop()
            merged.append(
                ChatMessage(role=message.role, content=f"{previous.content}\n\n{message.content}")
            )
        else:
            merged.append(ChatMessage(role=message.role, content=message.content))

    kept: list[ChatMessage] = []
    used = 0
    for message in reversed(merged):
        cost = estimate_tokens(message.content)
        if kept and used + cost > budget_tokens:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    while kept and kept[0].role != "user":
        kept.pop(0)
    return kept


class AssistantService:
    def __init__(
        self,
        database: Database,
        ai: ModelRouter,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = database
        self._ai = ai
        self._clock = clock

    # ------------------------------------------------------------ conversations
    async def list_conversations(
        self, user_id: uuid.UUID, limit: int = 100
    ) -> list[AssistantConversation]:
        async with self._db.transaction(user_id) as session:
            rows = await session.scalars(
                select(AssistantConversation)
                .order_by(AssistantConversation.updated_at.desc())
                .limit(limit)
            )
            return list(rows)

    async def create_conversation(self, user_id: uuid.UUID) -> AssistantConversation:
        conversation = AssistantConversation(id=uuid.uuid4(), user_id=user_id, title=DEFAULT_TITLE)
        async with self._db.transaction(user_id) as session:
            session.add(conversation)
            await session.flush()
            await session.refresh(conversation)
        return conversation

    async def conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[AssistantConversation, list[AssistantMessage]]:
        async with self._db.transaction(user_id) as session:
            conversation = await session.get(AssistantConversation, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError
            messages = await session.scalars(
                select(AssistantMessage)
                .where(AssistantMessage.conversation_id == conversation_id)
                .order_by(AssistantMessage.created_at, AssistantMessage.id)
            )
            return conversation, list(messages)

    async def delete_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        async with self._db.transaction(user_id) as session:
            result = await session.execute(
                delete(AssistantConversation)
                .where(AssistantConversation.id == conversation_id)
                .returning(AssistantConversation.id)
            )
            if result.first() is None:
                raise ConversationNotFoundError

    # ------------------------------------------------------------------- un tour
    async def start_turn(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        text: str,
        config: AssistantConfig,
    ) -> Turn:
        """Enregistre le message de l'utilisateur et prepare la requete au modele.

        Leve ConversationNotFoundError avant toute ecriture si la conversation n'est pas a lui.
        """
        async with self._db.transaction(user_id) as session:
            conversation = await session.get(AssistantConversation, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError
            rows = await session.execute(
                select(AssistantMessage.role, AssistantMessage.content, AssistantMessage.status)
                .where(AssistantMessage.conversation_id == conversation_id)
                .order_by(AssistantMessage.created_at, AssistantMessage.id)
            )
            # Valeurs garanties par les contraintes CHECK de la migration assistant_0001.
            history = [
                StoredMessage(cast(Role, role), content, cast(MessageStatus, status))
                for role, content, status in rows
            ]
            await session.execute(
                insert(AssistantMessage).values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role="user",
                    content=text,
                    status="ok",
                )
            )
            values: dict[str, object] = {"updated_at": func.now()}
            if conversation.title == DEFAULT_TITLE and not history:
                values["title"] = title_from(text)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conversation_id)
                .values(**values)
            )

        now_local = self._clock().astimezone(ZoneInfo(config.timezone))
        messages = fit_history([*history, StoredMessage("user", text, "ok")], HISTORY_TOKENS)
        request = ChatRequest(
            system=system_prompt(config.display_name, now_local, config.timezone),
            messages=messages,
        )
        return Turn(user_id=user_id, conversation_id=conversation_id, request=request)

    async def play(self, turn: Turn) -> AsyncGenerator[ReplyEvent]:
        """Reponse en flux, puis Done. Toujours enregistree, meme si le client part."""
        parts: list[str] = []
        status: MessageStatus = "ok"
        reason = "ok"
        result: ChatResult | None = None
        saved = False

        async def save() -> uuid.UUID:
            nonlocal saved
            saved = True
            content = "".join(parts) or FALLBACKS["error"]
            return await self._save_reply(turn, content, status, result)

        try:
            try:
                async for event in self._ai.chat_stream(
                    turn.user_id, task=TASK, data_class="personal", request=turn.request
                ):
                    if isinstance(event, TextDelta):
                        parts.append(event.text)
                        yield Delta(event.text)
                    else:
                        result = event
            except AIUnavailableError as error:
                status, reason = "fallback", error.reason
                key = "budget" if error.reason == "budget" else "unavailable"
                parts[:] = [FALLBACKS[key]]
                yield Delta(FALLBACKS[key])
            except AIRefusedError as error:
                status, reason = "fallback", error.reason
                key = "too_long" if error.reason == "too_long" else "refused"
                parts[:] = [FALLBACKS[key]]
                yield Delta(FALLBACKS[key])
            except AIInterruptedError:
                status, reason = "interrupted", "provider"
            except Exception:
                # Bogue : l'utilisateur recoit un gabarit, la trace complete part au journal.
                log.exception("assistant_reply_failed")
                status, reason = "fallback", "error"
                parts[:] = [FALLBACKS["error"]]
                yield Delta(FALLBACKS["error"])

            message_id = await save()
            REPLIES.labels(status=status, reason=reason).inc()
            yield Done(
                message_id=message_id,
                status=status,
                budget_warning=result.budget_warning if result else False,
            )
        finally:
            if not saved:
                # Client parti en cours de reponse : on garde ce qui a ete genere. Protege de
                # l'annulation en cours, sinon l'ecriture serait annulee a son tour.
                status, reason = "interrupted", "client_left"
                with anyio.CancelScope(shield=True):
                    if parts:
                        try:
                            await save()
                        except Exception:  # ex. conversation supprimee pendant la reponse
                            log.exception("assistant_partial_reply_not_saved")
                REPLIES.labels(status=status, reason=reason).inc()

    async def _save_reply(
        self, turn: Turn, content: str, status: MessageStatus, result: ChatResult | None
    ) -> uuid.UUID:
        message_id = uuid.uuid4()
        cost: Decimal | None = result.cost_usd if result else None
        async with self._db.transaction(turn.user_id) as session:
            await session.execute(
                insert(AssistantMessage).values(
                    id=message_id,
                    user_id=turn.user_id,
                    conversation_id=turn.conversation_id,
                    role="assistant",
                    content=content,
                    status=status,
                    provider=result.provider if result else None,
                    model=result.model if result else None,
                    prompt_version=PROMPT_VERSION if status != "fallback" else None,
                    cost_usd=cost,
                )
            )
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == turn.conversation_id)
                .values(updated_at=func.now())
            )
        return message_id
