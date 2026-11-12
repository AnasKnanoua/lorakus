"""Adaptateur Anthropic (API Messages en streaming) derriere le port AIProvider.

Seul fichier de Lorakus a importer le SDK `anthropic` (verifie par test). Il traduit la
requete, lit les evenements du flux, et convertit toute erreur du SDK en ProviderError.
"""

from collections.abc import AsyncIterator
from typing import Final

import anthropic
from anthropic.types import AssistantMessageParam, MessageParam, UserMessageParam

from lorakus.ai.port import (
    Capabilities,
    ChatMessage,
    ChatRequest,
    Completion,
    ProviderError,
    StreamEvent,
    TextDelta,
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
        return UserMessageParam(role="user", content=message.content)
    return AssistantMessageParam(role="assistant", content=message.content)


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
        return Capabilities(external=True)

    async def chat_stream(self, model: str, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        messages = [_message(m) for m in request.messages]
        input_tokens = output_tokens = cache_read = cache_write = 0
        stop_reason = "end_turn"
        try:
            stream = await self._client.messages.create(
                model=model,
                max_tokens=request.max_output_tokens,
                system=request.system,
                messages=messages,
                stream=True,
            )
            async with stream:
                async for event in stream:
                    if event.type == "message_start":
                        usage = event.message.usage
                        input_tokens = usage.input_tokens
                        cache_read = usage.cache_read_input_tokens or 0
                        cache_write = usage.cache_creation_input_tokens or 0
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta" and event.delta.text:
                            yield TextDelta(event.delta.text)
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
