"""Adaptateur Anthropic (API Messages en streaming) derriere le port AIProvider.

Seul fichier de Lorakus a importer le SDK `anthropic` (verifie par test). Il traduit la
requete, lit les evenements du flux, et convertit toute erreur du SDK en ProviderError.

Outils (PR 38) : les definitions et les blocs tool_use / tool_result sont traduits tels quels.
Les arguments d'un appel arrivent en morceaux de JSON (input_json_delta) : ils sont
reassembles, puis l'appel est emis a la fin de son bloc. Un JSON illisible donne un appel
sans argument : la validation par schema de l'appelant le refusera.
"""

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any, Final

import anthropic
from anthropic.types import (
    AssistantMessageParam,
    MessageParam,
    TextBlockParam,
    ToolChoiceAutoParam,
    ToolChoiceNoneParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
    UserMessageParam,
)

from lorakus.ai.port import (
    Capabilities,
    ChatMessage,
    ChatRequest,
    Completion,
    ProviderError,
    StreamEvent,
    TextDelta,
    ToolDefinition,
    ToolUse,
    ToolUseEvent,
    Usage,
)

# Une seule nouvelle tentative du SDK (erreurs reseau et 5xx) : au-dela, le routeur passe
# au repli plutot que de laisser l'utilisateur attendre.
MAX_RETRIES: Final = 1
TIMEOUT_S: Final = 30.0


def _translate(error: anthropic.AnthropicError) -> ProviderError:
    """Erreur du SDK -> ProviderError. Le message ne contient jamais la cle."""
    if isinstance(error, anthropic.RateLimitError):
        return ProviderError("rate_limited", "limite de debit du fournisseur atteinte")
    if isinstance(error, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ProviderError("misconfigured", "cle d'API refusee par le fournisseur")
    if isinstance(
        error,
        anthropic.BadRequestError
        | anthropic.NotFoundError
        | anthropic.RequestTooLargeError
        | anthropic.UnprocessableEntityError,
    ):
        return ProviderError("rejected", f"requete refusee ({type(error).__name__})")
    return ProviderError("unavailable", f"fournisseur indisponible ({type(error).__name__})")


def _message(message: ChatMessage) -> MessageParam:
    if message.role == "user":
        if not message.tool_results:
            return UserMessageParam(role="user", content=message.content)
        blocks: list[ToolResultBlockParam | TextBlockParam] = [
            ToolResultBlockParam(
                type="tool_result",
                tool_use_id=r.tool_use_id,
                content=r.content,
                is_error=r.is_error,
            )
            for r in message.tool_results
        ]
        if message.content:
            blocks.append(TextBlockParam(type="text", text=message.content))
        return UserMessageParam(role="user", content=blocks)
    if not message.tool_uses:
        return AssistantMessageParam(role="assistant", content=message.content)
    parts: list[TextBlockParam | ToolUseBlockParam] = []
    if message.content:
        parts.append(TextBlockParam(type="text", text=message.content))
    parts.extend(
        ToolUseBlockParam(type="tool_use", id=u.id, name=u.name, input=dict(u.input))
        for u in message.tool_uses
    )
    return AssistantMessageParam(role="assistant", content=parts)


def _tools(definitions: Iterable[ToolDefinition]) -> list[ToolParam]:
    return [
        ToolParam(name=d.name, description=d.description, input_schema=dict(d.input_schema))
        for d in definitions
    ]


def _parse_input(raw: str) -> dict[str, Any]:
    """Arguments reassembles ; tout ce qui n'est pas un objet JSON donne {}."""
    if not raw.strip():
        return {}
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}  # type: ignore[return-value]


class AnthropicProvider:
    def __init__(self, api_key: str, *, client: anthropic.AsyncAnthropic | None = None) -> None:
        if client is None and not api_key:
            raise ValueError("cle Anthropic absente")
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=MAX_RETRIES, timeout=TIMEOUT_S
        )

    @property
    def name(self) -> str:
        return "anthropic"

    def capabilities(self) -> Capabilities:
        return Capabilities(external=True, tools=True)

    async def chat_stream(self, model: str, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        messages = [_message(m) for m in request.messages]
        input_tokens = output_tokens = cache_read = cache_write = 0
        stop_reason = "end_turn"
        # Appels d'outils en cours de reception, par index de bloc : (id, nom, JSON partiel).
        pending: dict[int, tuple[str, str, list[str]]] = {}
        extra: dict[str, Any] = {}
        if request.tools:
            extra["tools"] = _tools(request.tools)
            extra["tool_choice"] = (
                ToolChoiceNoneParam(type="none")
                if request.tool_choice == "none"
                else ToolChoiceAutoParam(type="auto")
            )
        try:
            stream = await self._client.messages.create(
                model=model,
                max_tokens=request.max_output_tokens,
                system=request.system,
                messages=messages,
                stream=True,
                **extra,
            )
            async with stream:
                async for event in stream:
                    if event.type == "message_start":
                        usage = event.message.usage
                        input_tokens = usage.input_tokens
                        cache_read = usage.cache_read_input_tokens or 0
                        cache_write = usage.cache_creation_input_tokens or 0
                    elif event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            pending[event.index] = (block.id, block.name, [])
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta" and event.delta.text:
                            yield TextDelta(event.delta.text)
                        elif event.delta.type == "input_json_delta" and event.index in pending:
                            pending[event.index][2].append(event.delta.partial_json)
                    elif event.type == "content_block_stop" and event.index in pending:
                        tool_id, name, chunks = pending.pop(event.index)
                        yield ToolUseEvent(
                            ToolUse(id=tool_id, name=name, input=_parse_input("".join(chunks)))
                        )
                    elif event.type == "message_delta":
                        # Compteurs cumules : la derniere valeur est la bonne.
                        output_tokens = event.usage.output_tokens
                        input_tokens = event.usage.input_tokens or input_tokens
                        cache_read = event.usage.cache_read_input_tokens or cache_read
                        cache_write = event.usage.cache_creation_input_tokens or cache_write
                        if event.delta.stop_reason is not None:
                            stop_reason = event.delta.stop_reason
        except anthropic.AnthropicError as error:
            raise _translate(error) from None
        yield Completion(
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
            stop_reason=stop_reason,
        )
