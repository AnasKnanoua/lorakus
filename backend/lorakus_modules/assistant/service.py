"""Conversations de l'assistant : un tour = message de l'utilisateur -> reponse en flux.

Tout passe par le ModelRouter (jamais un SDK). Quand l'IA est indisponible ou refuse, la
reponse est un gabarit fixe (scenario 8 du MVP) : l'utilisateur sait toujours ce qui se
passe, et son message est enregistre dans tous les cas.

Le prompt envoye est borne : seuls les derniers messages tiennent dans HISTORY_TOKENS, pour
que le cout d'un message reste petit meme dans une longue conversation.

Outils (PR 38) : le modele peut demander les outils du profil assistant (CHAT_TOOLS), tous
executes par le ToolRuntime. Un outil read rend son resultat au modele ; un outil write ou
sensitive produit une CARTE pour l'utilisateur, et le modele apprend seulement qu'elle attend
sa confirmation (jamais son identifiant : il ne peut pas la confirmer). Au plus
MAX_MODEL_CALLS appels au modele par message, le dernier sans outil ; au plus
MAX_TOOL_CALLS appels d'outils et MAX_CARDS cartes.
"""

import json
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal, cast
from zoneinfo import ZoneInfo

import anyio
import structlog
from prometheus_client import Counter
from sqlalchemy import delete, func, insert, select, update

from lorakus.ai.port import (
    ChatMessage,
    ChatRequest,
    TextDelta,
    ToolDefinition,
    ToolResult,
    ToolUse,
    ToolUseEvent,
    estimate_tokens,
)
from lorakus.ai.router import (
    AIInterruptedError,
    AIRefusedError,
    AIUnavailableError,
    ChatResult,
    ModelRouter,
)
from lorakus.core.agents.orchestrator import Consultation, Orchestrator
from lorakus.core.agents.routing import IntentRouter, Routing
from lorakus.core.background import DebouncedTasks
from lorakus.core.memory.service import MemoryService, SourceMessage
from lorakus.core.tools.runtime import ConfirmationStatus, ToolRuntime
from lorakus.core.tools.spec import ToolError, ToolSpec
from lorakus.db.database import Database
from lorakus_modules.assistant.config import AssistantConfig
from lorakus_modules.assistant.models import AssistantConversation, AssistantMessage
from lorakus_modules.assistant.prompts import PROMPT_VERSION, reports_block, system_prompt

log = structlog.get_logger("lorakus.assistant")

TASK: Final = "chat"
HISTORY_TOKENS: Final = 6000  # environ 0,0006 $ d'entree par message avec Haiku 5.5
MAX_MESSAGE_CHARS: Final = 8000
TITLE_CHARS: Final = 60
# Messages de l'utilisateur soumis au plus a une analyse de la memoire (les plus recents).
MEMORY_MESSAGES: Final = 20
# Raisons pour lesquelles les messages analyses sont consideres comme traites. Sinon (moteur IA
# indisponible, reponse invalide, propositions en attente au maximum), ils le seront plus tard.
_MEMORY_DONE: Final = frozenset({"ok", "empty", "disabled"})
DEFAULT_TITLE: Final = "Nouvelle conversation"

# Outils du profil assistant (SECURITY.md §7) : liste explicite. L'outil d'un futur module
# n'est propose au modele que s'il est ajoute ici, apres revue.
CHAT_TOOLS: Final = (
    "assistant.search_memory",
    "assistant.remember",
    "assistant.update_memory",
    "assistant.forget_memory",
)
MAX_MODEL_CALLS: Final = 4  # par message ; le dernier appel est sans outil
MAX_TOOL_CALLS: Final = 6  # par message
MAX_CARDS: Final = 3  # cartes de confirmation par message
# Ce que le modele recoit pour une action mise en attente : jamais l'identifiant de la carte.
PENDING_FOR_MODEL: Final = (
    "Carte de confirmation affichée à l'utilisateur. Rien n'est fait tant qu'il ne l'a pas "
    "confirmée lui-même : ne dis pas que c'est fait, et ne redemande pas la même action."
)
CARD_STATUS_FOR_MODEL: Final[dict[str, str]] = {
    "pending": "en attente de sa confirmation",
    "confirmed": "confirmée par l'utilisateur",
    "cancelled": "refusée par l'utilisateur",
    "expired": "expirée sans réponse",
}

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
        "de langage avant le 1er du mois prochain. Ton message est bien enregistré."
    ),
    "unavailable": (
        "Mon modèle de langage est indisponible pour le moment. Réessaie dans quelques "
        "minutes ; ton message est bien enregistré."
    ),
    "rate_limited": (
        "Tu m'envoies beaucoup de messages d'un coup : je marque une courte pause pour "
        "protéger ton budget d'IA. Réessaie dans une minute ; ton message est bien enregistré."
    ),
    "too_long": (
        "Ce message est trop long pour que je le traite en une fois. Peux-tu le raccourcir "
        "ou le découper ?"
    ),
    "refused": "Je ne peux pas envoyer ces données à un modèle externe.",
    "error": "Une erreur interne m'empêche de répondre. Elle a été signalée ; réessaie plus tard.",
}


class ConversationNotFoundError(Exception):
    """Conversation absente ou appartenant a un autre utilisateur (la RLS les confond)."""


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Activity:
    """Un outil read a servi (ou a echoue) : indication discrete dans le chat."""

    tool: str
    label: str
    ok: bool = True


@dataclass(frozen=True)
class Card:
    """Action en attente de la confirmation de l'utilisateur (texte ecrit par l'outil)."""

    confirmation_id: uuid.UUID
    tool: str
    risk: str
    summary: str
    expires_at: datetime


@dataclass(frozen=True)
class Done:
    message_id: uuid.UUID
    status: MessageStatus
    budget_warning: bool


ReplyEvent = Delta | Activity | Card | Done


@dataclass(frozen=True)
class StoredMessage:
    role: Role
    content: str
    status: MessageStatus


@dataclass(frozen=True)
class Turn:
    """Tour pret a etre joue : tout ce qui peut echouer avec une 404 est deja verifie.

    tools : outils proposes au modele, par nom « fil » (sans point, voir wire_name).
    """

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    request: ChatRequest
    tools: dict[str, ToolSpec] = field(default_factory=dict[str, ToolSpec])
    ip: str | None = None
    # Identifiant de la reponse, fixe des le debut : les consultations des specialistes y
    # sont reliees (core_agent_runs.trace_id) avant meme qu'elle soit ecrite.
    reply_id: uuid.UUID = field(default_factory=uuid.uuid4)
    # Ce que la trace « Pourquoi ? » dira de la preparation (souvenirs, routage, specialistes).
    trace: dict[str, object] = field(default_factory=dict[str, object])

    @property
    def origin(self) -> str:
        return f"conversation:{self.conversation_id}"


def wire_name(tool_name: str) -> str:
    """Nom d'outil accepte par les fournisseurs : `module.action` -> `module__action`."""
    return tool_name.replace(".", "__")


def tool_definitions(specs: Sequence[ToolSpec]) -> dict[str, ToolSpec]:
    """Outils autorises pour le chat, indexes par nom fil (un doublon est une erreur)."""
    allowed = {s.name: s for s in specs if s.name in CHAT_TOOLS}
    named = {wire_name(name): spec for name, spec in sorted(allowed.items())}
    if len(named) != len(allowed):
        raise ValueError("deux outils ont le meme nom fil")
    return named


def card_note(summary: str, status: str) -> str:
    """Rappel, pour le modele, d'une carte d'un message precedent et de son issue."""
    line = " ".join(summary.split())
    return f"[Carte proposée : {line} ; {CARD_STATUS_FOR_MODEL.get(status, status)}]"


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
        *,
        memory: MemoryService | None = None,
        background: DebouncedTasks | None = None,
        memory_delay_s: float = 180,
        tools: ToolRuntime | None = None,
        orchestrator: Orchestrator | None = None,
        intent_router: IntentRouter | None = None,
    ) -> None:
        self._db = database
        self._ai = ai
        self._clock = clock
        self._memory = memory
        self._tools = tools
        self._orchestrator = orchestrator
        self._intent_router = intent_router or IntentRouter()
        self._background = background
        self._memory_delay_s = memory_delay_s

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

    async def reply(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> AssistantMessage:
        """Une reponse de l'assistant (ConversationNotFoundError si absente ou d'un autre)."""
        async with self._db.transaction(user_id) as session:
            message = await session.scalar(
                select(AssistantMessage).where(
                    AssistantMessage.id == message_id,
                    AssistantMessage.conversation_id == conversation_id,
                    AssistantMessage.role == "assistant",
                )
            )
        if message is None:
            raise ConversationNotFoundError
        return message

    async def card_statuses(
        self, user_id: uuid.UUID, messages: Sequence[AssistantMessage]
    ) -> dict[uuid.UUID, ConfirmationStatus]:
        """Issue actuelle de chaque carte des messages (confirmee, refusee, expiree...)."""
        ids = [
            uuid.UUID(str(action["confirmation_id"]))
            for message in messages
            for action in message.actions
            if action.get("kind") == "card"
        ]
        if not ids or self._tools is None:
            return {}
        return await self._tools.statuses(user_id, ids)

    async def delete_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        async with self._db.transaction(user_id) as session:
            result = await session.execute(
                delete(AssistantConversation)
                .where(AssistantConversation.id == conversation_id)
                .returning(AssistantConversation.id)
            )
            if result.first() is None:
                raise ConversationNotFoundError
        if self._tools is not None:
            # Les actions de la conversation ne peuvent plus etre confirmees ; leurs arguments
            # (qui citent la conversation) sont effaces.
            await self._tools.retire_origin(user_id, f"conversation:{conversation_id}")

    # ------------------------------------------------------------------- un tour
    async def start_turn(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        text: str,
        config: AssistantConfig,
        ip: str | None = None,
    ) -> Turn:
        """Enregistre le message de l'utilisateur et prepare la requete au modele.

        Leve ConversationNotFoundError avant toute ecriture si la conversation n'est pas a lui.
        """
        async with self._db.transaction(user_id) as session:
            conversation = await session.get(AssistantConversation, conversation_id)
            if conversation is None:
                raise ConversationNotFoundError
            stored = list(
                await session.scalars(
                    select(AssistantMessage)
                    .where(AssistantMessage.conversation_id == conversation_id)
                    .order_by(AssistantMessage.created_at, AssistantMessage.id)
                )
            )
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
            if conversation.title == DEFAULT_TITLE and not stored:
                values["title"] = title_from(text)
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == conversation_id)
                .values(**values)
            )

        history = await self._history(user_id, stored)
        now_local = self._clock().astimezone(ZoneInfo(config.timezone))
        messages = fit_history([*history, StoredMessage("user", text, "ok")], HISTORY_TOKENS)
        facts = await self._memory.prompt_facts(user_id, text) if self._memory else []
        tools = tool_definitions(await self._tools.available(user_id)) if self._tools else {}
        reply_id = uuid.uuid4()
        routing, consultations = await self._consult(user_id, text, reply_id)
        request = ChatRequest(
            system=system_prompt(
                config.display_name,
                now_local,
                config.timezone,
                [(f.category, f.content) for f in facts],
                tools=bool(tools),
                reports=reports_block(consultations),
            ),
            messages=messages,
            tools=tuple(
                ToolDefinition(
                    name=name,
                    description=spec.description,
                    input_schema=spec.input_model.model_json_schema(),
                )
                for name, spec in tools.items()
            ),
        )
        self._schedule_memory(user_id, conversation_id)
        trace: dict[str, object] = {
            "prompt_version": PROMPT_VERSION,
            "memory_fact_ids": [str(f.id) for f in facts],
            "routing": _routing_trace(routing),
            "specialists": [_consultation_trace(c) for c in consultations],
        }
        return Turn(
            user_id=user_id,
            conversation_id=conversation_id,
            request=request,
            tools=tools,
            ip=ip,
            reply_id=reply_id,
            trace=trace,
        )

    async def _consult(
        self, user_id: uuid.UUID, question: str, reply_id: uuid.UUID
    ) -> tuple[Routing | None, list[Consultation]]:
        """Routage puis consultation des specialistes (PR 39). Sans specialiste actif : rien,
        pas meme un calcul d'embedding (aucun cout ajoute au chat)."""
        if self._orchestrator is None:
            return None, []
        profiles = await self._orchestrator.agents.available(user_id)
        if not profiles:
            return None, []
        routing = await self._intent_router.route(question, profiles)
        if not routing.targets:
            return routing, []
        consultations = await self._orchestrator.consult(
            user_id, routing.targets, trace_id=str(reply_id)
        )
        return routing, consultations

    async def _history(
        self, user_id: uuid.UUID, stored: Sequence[AssistantMessage]
    ) -> list[StoredMessage]:
        """Messages pour le modele ; les cartes d'une reponse y sont rappelees avec leur issue
        (texte ecrit par le code : le modele sait ce que l'utilisateur a confirme ou refuse)."""
        statuses = await self.card_statuses(user_id, stored)
        history: list[StoredMessage] = []
        for message in stored:
            content = message.content
            notes = [
                card_note(
                    str(action["summary"]),
                    statuses.get(uuid.UUID(str(action["confirmation_id"])), "expired"),
                )
                for action in message.actions
                if action.get("kind") == "card"
            ]
            if notes:
                content = "\n\n".join([content, *notes]) if content.strip() else "\n".join(notes)
            # Valeurs garanties par les contraintes CHECK de la migration assistant_0001.
            history.append(
                StoredMessage(
                    cast(Role, message.role), content, cast(MessageStatus, message.status)
                )
            )
        return history

    # ------------------------------------------------------------------ memoire
    def _schedule_memory(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        """Analyse differee : un nouveau message de la conversation repousse l'analyse."""
        if self._memory is None or self._background is None:
            return
        self._background.schedule(
            f"memory:{conversation_id}",
            self._memory_delay_s,
            lambda: self.propose_memory(user_id, conversation_id),
        )

    async def propose_memory(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
        """Propose des faits a partir des messages de l'utilisateur pas encore analyses.

        Seuls les messages de l'utilisateur sont lus, jamais les reponses de l'assistant.
        Renvoie la raison de l'issue (journalisee par le service de memoire).
        """
        if self._memory is None:
            return "disabled"
        async with self._db.transaction(user_id) as session:
            conversation = await session.get(AssistantConversation, conversation_id)
            if conversation is None:
                return "gone"  # supprimee entre-temps
            query = select(
                AssistantMessage.id, AssistantMessage.content, AssistantMessage.created_at
            ).where(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.role == "user",
            )
            if conversation.memory_scanned_until is not None:
                query = query.where(AssistantMessage.created_at > conversation.memory_scanned_until)
            rows = list(
                await session.execute(
                    query.order_by(
                        AssistantMessage.created_at.desc(), AssistantMessage.id.desc()
                    ).limit(MEMORY_MESSAGES)
                )
            )
        if not rows:
            return "empty"
        rows.reverse()
        outcome = await self._memory.propose_from_messages(
            user_id,
            source_ref=f"conversation:{conversation_id}",
            messages=[SourceMessage(id=row.id, text=row.content) for row in rows],
        )
        if outcome.reason in _MEMORY_DONE:
            async with self._db.transaction(user_id) as session:
                await session.execute(
                    update(AssistantConversation)
                    .where(AssistantConversation.id == conversation_id)
                    .values(memory_scanned_until=rows[-1].created_at)
                )
        return outcome.reason

    async def play(self, turn: Turn) -> AsyncGenerator[ReplyEvent]:
        """Reponse en flux (texte, outils, cartes), puis Done. Toujours enregistree, meme si
        le client part."""
        parts: list[str] = []
        actions: list[dict[str, object]] = []
        status: MessageStatus = "ok"
        reason = "ok"
        result: ChatResult | None = None
        cost = Decimal(0)
        calls = 0  # appels au modele reussis pour ce message
        budget_warning = False
        saved = False

        async def save() -> uuid.UUID:
            nonlocal saved
            saved = True
            content = "".join(parts).strip() or (
                "Voici ce que je te propose." if actions else FALLBACKS["error"]
            )
            trace = {
                **turn.trace,
                "model": result.model if result else None,
                "model_calls": calls,
                "cost_usd": str(cost) if result else None,
                "data_classes_sent": _classes_sent(turn, calls),
            }
            return await self._save_reply(turn, content, status, result, cost, actions, trace)

        def fallback(key: str) -> Delta:
            # Avant tout texte et toute carte : la reponse est le gabarit. Apres : on garde ce
            # qui a ete montre (cartes comprises) et la reponse est marquee interrompue.
            nonlocal status
            if parts or actions:
                status = "interrupted"
                return Delta("")
            status = "fallback"
            parts[:] = [FALLBACKS[key]]
            return Delta(FALLBACKS[key])

        try:
            try:
                messages = list(turn.request.messages)
                counters = {"tools": 0, "cards": 0}
                for call_index in range(MAX_MODEL_CALLS if turn.tools else 1):
                    last = call_index == MAX_MODEL_CALLS - 1
                    request = turn.request.model_copy(
                        update={
                            # Copie : la requete d'un tour ne change plus une fois envoyee.
                            "messages": list(messages),
                            "tool_choice": "none" if last else "auto",
                        }
                    )
                    round_text: list[str] = []
                    uses: list[ToolUse] = []
                    async for event in self._ai.chat_stream(
                        turn.user_id,
                        task=TASK,
                        data_class="personal",
                        request=request,
                        continuation=call_index > 0,
                    ):
                        if isinstance(event, TextDelta):
                            if not round_text and parts and not parts[-1].endswith(("\n", " ")):
                                parts.append("\n\n")  # texte d'un nouveau tour : un paragraphe
                                yield Delta("\n\n")
                            round_text.append(event.text)
                            parts.append(event.text)
                            yield Delta(event.text)
                        elif isinstance(event, ToolUseEvent):
                            uses.append(event.tool_use)
                        else:
                            result = event
                            cost += event.cost_usd
                            calls += 1
                            budget_warning = budget_warning or event.budget_warning
                    if not uses or last:
                        break
                    messages.append(
                        ChatMessage(
                            role="assistant", content="".join(round_text), tool_uses=tuple(uses)
                        )
                    )
                    results: list[ToolResult] = []
                    for use in uses:
                        content, is_error, shown = await self._run_tool(turn, use, counters)
                        if shown is not None:
                            actions.append(_action(shown))
                            yield shown
                        results.append(
                            ToolResult(tool_use_id=use.id, content=content, is_error=is_error)
                        )
                    messages.append(ChatMessage(role="user", tool_results=tuple(results)))
            except AIUnavailableError as error:
                reason = error.reason
                key = error.reason if error.reason in ("budget", "rate_limited") else "unavailable"
                notice = fallback(key)
                if notice.text:
                    yield notice
            except AIRefusedError as error:
                reason = error.reason
                notice = fallback("too_long" if error.reason == "too_long" else "refused")
                if notice.text:
                    yield notice
            except AIInterruptedError:
                status, reason = "interrupted", "provider"
            except Exception:
                # Bogue : l'utilisateur recoit un gabarit, la trace complete part au journal.
                log.exception("assistant_reply_failed")
                reason = "error"
                notice = fallback("error")
                if notice.text:
                    yield notice

            message_id = await save()
            REPLIES.labels(status=status, reason=reason).inc()
            yield Done(message_id=message_id, status=status, budget_warning=budget_warning)
        finally:
            if not saved:
                # Client parti en cours de reponse : on garde ce qui a ete genere (et les
                # cartes deja montrees). Protege de l'annulation en cours, sinon l'ecriture
                # serait annulee a son tour.
                status, reason = "interrupted", "client_left"
                with anyio.CancelScope(shield=True):
                    if parts or actions:
                        try:
                            await save()
                        except Exception:  # ex. conversation supprimee pendant la reponse
                            log.exception("assistant_partial_reply_not_saved")
                REPLIES.labels(status=status, reason=reason).inc()

    async def _run_tool(
        self, turn: Turn, use: ToolUse, counters: dict[str, int]
    ) -> tuple[str, bool, Activity | Card | None]:
        """Execute une demande du modele par le ToolRuntime.

        Renvoie (resultat pour le modele, erreur ?, evenement a montrer). Le resultat est une
        DONNEE (JSON ou texte fixe) ; pour une carte, jamais son identifiant.
        """
        spec = turn.tools.get(use.name)
        if spec is None or self._tools is None:
            return _for_model({"erreur": "outil inconnu"}), True, None
        counters["tools"] += 1
        if counters["tools"] > MAX_TOOL_CALLS:
            return _for_model({"erreur": "trop d'appels d'outils pour ce message"}), True, None
        if spec.risk != "read" and counters["cards"] >= MAX_CARDS:
            return _for_model({"erreur": "trop d'actions proposées pour ce message"}), True, None
        label = spec.activity or spec.description
        try:
            outcome = await self._tools.call(
                turn.user_id, spec.name, use.input, turn.ip, origin=turn.origin
            )
        except ToolError as error:
            shown = Activity(spec.name, label, ok=False) if spec.risk == "read" else None
            return _for_model({"erreur": str(error)}), True, shown
        if outcome.confirmation_id is None:
            return _for_model(outcome.result or {}), False, Activity(spec.name, label)
        if outcome.summary is None or outcome.expires_at is None:  # garanti par ToolRuntime
            return _for_model({"erreur": "action impossible a decrire"}), True, None
        counters["cards"] += 1
        card = Card(
            confirmation_id=outcome.confirmation_id,
            tool=spec.name,
            risk=spec.risk,
            summary=outcome.summary,
            expires_at=outcome.expires_at,
        )
        return PENDING_FOR_MODEL, False, card

    async def _save_reply(
        self,
        turn: Turn,
        content: str,
        status: MessageStatus,
        result: ChatResult | None,
        cost: Decimal,
        actions: list[dict[str, object]],
        trace: dict[str, object],
    ) -> uuid.UUID:
        message_id = turn.reply_id
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
                    cost_usd=cost if result else None,
                    actions=actions,
                    trace=trace,
                )
            )
            await session.execute(
                update(AssistantConversation)
                .where(AssistantConversation.id == turn.conversation_id)
                .values(updated_at=func.now())
            )
        return message_id


def _routing_trace(routing: Routing | None) -> dict[str, object] | None:
    if routing is None:
        return None
    return {
        "tier": routing.tier,
        "best": routing.best,
        "score": routing.score,
        "runner_up": routing.runner_up,
        "reason": routing.reason,
    }


def _consultation_trace(c: Consultation) -> dict[str, object]:
    return {
        "specialist": c.specialist,
        "display_name": c.display_name,
        "intent": c.intent,
        "status": c.report.status,
        "duration_ms": c.duration_ms,
        "cached": c.cached,
        "skipped": c.skipped,
        "data_classes": list(c.data_classes),
    }


def _classes_sent(turn: Turn, calls: int) -> list[str]:
    """Classes de donnees parties chez le fournisseur pour ce message (ADR 0026)."""
    if calls == 0:
        return []
    classes = {"personal"}  # la conversation elle-meme
    for item in cast(list[dict[str, object]], turn.trace.get("specialists", [])):
        classes.update(cast(list[str], item["data_classes"]))
    order = {"public": 0, "personal": 1, "sensitive": 2}
    return sorted(classes, key=lambda c: order.get(c, 9))


def _for_model(data: dict[str, object]) -> str:
    """Resultat d'outil pour le modele : du JSON, jamais une consigne."""
    return json.dumps(data, ensure_ascii=False, default=str)


def _action(event: Activity | Card) -> dict[str, object]:
    """Trace d'un outil enregistree avec la reponse (reaffichee au rechargement)."""
    if isinstance(event, Activity):
        return {"kind": "activity", "tool": event.tool, "label": event.label, "ok": event.ok}
    return {
        "kind": "card",
        "confirmation_id": str(event.confirmation_id),
        "tool": event.tool,
        "risk": event.risk,
        "summary": event.summary,
        "expires_at": event.expires_at.isoformat(),
    }
