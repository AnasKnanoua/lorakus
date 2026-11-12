"""Adaptateur Anthropic : le vrai SDK, face a un faux serveur HTTP (aucun appel reseau).

Le faux serveur repond avec le format de flux de l'API Messages (Server-Sent Events) :
le SDK le lit comme en production, seul le transport HTTP est remplace.
"""

import json
from collections.abc import Callable

import anthropic
import httpx2
import pytest

from lorakus.ai.port import ChatMessage, ChatRequest, Completion, ProviderError, TextDelta
from lorakus.ai.providers.anthropic import AnthropicProvider

pytestmark = pytest.mark.anyio

SECRET = "sk-ant-ne-doit-jamais-apparaitre"


def sse(*events: tuple[str, dict[str, object]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


HAPPY_STREAM = sse(
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 42,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 7,
                    "cache_creation_input_tokens": 0,
                },
            },
        },
    ),
    (
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    ),
    (
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Bon"}},
    ),
    ("ping", {"type": "ping"}),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "jour"},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
)


def make_provider(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[AnthropicProvider, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    client = anthropic.AsyncAnthropic(
        api_key=SECRET,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recording)),
    )
    return AnthropicProvider("", client=client), seen


def streaming(body: bytes) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


def error(status: int, kind: str) -> Callable[[httpx2.Request], httpx2.Response]:
    payload = {"type": "error", "error": {"type": kind, "message": "refus"}}
    return lambda _: httpx2.Response(status, json=payload)


REQUEST = ChatRequest(
    system="Tu es Lorakus.",
    messages=[
        ChatMessage(role="user", content="Salut"),
        ChatMessage(role="assistant", content="Bonjour !"),
        ChatMessage(role="user", content="Ca va ?"),
    ],
    max_output_tokens=256,
)


async def test_streams_text_and_reports_usage() -> None:
    provider, _ = make_provider(streaming(HAPPY_STREAM))

    events = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]

    assert events[:2] == [TextDelta("Bon"), TextDelta("jour")]
    completion = events[-1]
    assert isinstance(completion, Completion)
    assert completion.stop_reason == "end_turn"
    assert completion.usage.input_tokens == 42
    assert completion.usage.output_tokens == 5
    assert completion.usage.cache_read_tokens == 7


async def test_sends_exactly_the_conversation_and_nothing_else() -> None:
    provider, seen = make_provider(streaming(HAPPY_STREAM))

    _ = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]

    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/messages"
    assert body == {
        "model": "claude-haiku-5-5",
        "max_tokens": 256,
        "system": "Tu es Lorakus.",
        "messages": [
            {"role": "user", "content": "Salut"},
            {"role": "assistant", "content": "Bonjour !"},
            {"role": "user", "content": "Ca va ?"},
        ],
        "stream": True,
    }
    # Le SDK 2.3 transmet la cle en en-tete Authorization, jamais dans le corps.
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"
    assert SECRET not in seen[0].content.decode()


@pytest.mark.parametrize(
    ("status", "kind", "expected"),
    [
        (429, "rate_limit_error", "rate_limited"),
        (401, "authentication_error", "misconfigured"),
        (403, "permission_error", "misconfigured"),
        (400, "invalid_request_error", "rejected"),
        (500, "api_error", "unavailable"),
        (529, "overloaded_error", "unavailable"),
    ],
)
async def test_http_errors_become_provider_errors(status: int, kind: str, expected: str) -> None:
    provider, _ = make_provider(error(status, kind))

    with pytest.raises(ProviderError) as raised:
        _ = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]

    assert raised.value.kind == expected
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is None  # le detail du SDK (requete, en-tetes) ne remonte pas


async def test_error_in_the_middle_of_the_stream_is_a_provider_error() -> None:
    broken = HAPPY_STREAM.split(b"event: content_block_stop")[0] + sse(
        ("error", {"type": "error", "error": {"type": "overloaded_error", "message": "surcharge"}})
    )
    provider, _ = make_provider(streaming(broken))
    received: list[object] = []

    with pytest.raises(ProviderError):
        async for event in provider.chat_stream("claude-haiku-5-5", REQUEST):
            received.append(event)

    assert received == [TextDelta("Bon"), TextDelta("jour")]


async def test_network_failure_is_unavailable() -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("reseau coupe", request=request)

    provider, _ = make_provider(down)

    with pytest.raises(ProviderError) as raised:
        _ = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]

    assert raised.value.kind == "unavailable"


def test_refuses_to_start_without_a_key() -> None:
    with pytest.raises(ValueError, match="cle Anthropic absente"):
        AnthropicProvider("")


def test_is_declared_external() -> None:
    provider, _ = make_provider(streaming(HAPPY_STREAM))

    assert provider.capabilities().external
    assert provider.name == "anthropic"
