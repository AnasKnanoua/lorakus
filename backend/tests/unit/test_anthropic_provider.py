"""Adaptateur Anthropic : le vrai SDK, face a un faux serveur HTTP (aucun appel reseau).

Le faux serveur repond avec le format de flux de l'API Messages (Server-Sent Events) :
le SDK le lit comme en production, seul le transport HTTP est remplace.
"""

import json
from collections.abc import Callable

import anthropic
import httpx2
import pytest

from lorakus.ai.port import (
    ChatMessage,
    ChatRequest,
    Completion,
    ProviderError,
    TextDelta,
    ToolDefinition,
    ToolResult,
    ToolUse,
    ToolUseEvent,
)
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


# ------------------------------------------------------------- outils (PR 38)
def _start(index: int, block: dict[str, object]) -> tuple[str, dict[str, object]]:
    return (
        "content_block_start",
        {"type": "content_block_start", "index": index, "content_block": block},
    )


def _json(index: int, partial: str) -> tuple[str, dict[str, object]]:
    return (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": "input_json_delta", "partial_json": partial},
        },
    )


def _stop(index: int) -> tuple[str, dict[str, object]]:
    return ("content_block_stop", {"type": "content_block_stop", "index": index})


TOOL_STREAM = sse(
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_2",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 120, "output_tokens": 1},
            },
        },
    ),
    _start(0, {"type": "text", "text": ""}),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Je cherche."},
        },
    ),
    _stop(0),
    _start(
        1, {"type": "tool_use", "id": "toolu_A", "name": "assistant__search_memory", "input": {}}
    ),
    _json(1, '{"quest'),
    _json(1, 'ion": "mat'),
    _json(1, 'in"}'),
    _stop(1),
    _start(2, {"type": "tool_use", "id": "toolu_B", "name": "assistant__remember", "input": {}}),
    _json(2, '{"content": tronque'),
    _stop(2),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 30},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
)

TOOLS_REQUEST = ChatRequest(
    system="Tu es Lorakus.",
    messages=[
        ChatMessage(role="user", content="Quand est-ce que je révise ?"),
        ChatMessage(
            role="assistant",
            content="Je regarde.",
            tool_uses=(
                ToolUse(
                    id="toolu_0", name="assistant__search_memory", input={"question": "réviser"}
                ),
            ),
        ),
        ChatMessage(
            role="user",
            tool_results=(ToolResult(tool_use_id="toolu_0", content='{"souvenirs": []}'),),
        ),
    ],
    tools=(
        ToolDefinition(
            name="assistant__search_memory",
            description="Cherche.",
            input_schema={"type": "object", "properties": {"question": {"type": "string"}}},
        ),
    ),
    tool_choice="none",
)


async def test_tool_calls_are_reassembled_from_json_fragments() -> None:
    provider, _ = make_provider(streaming(TOOL_STREAM))

    events = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]

    assert events[0] == TextDelta("Je cherche.")
    assert events[1] == ToolUseEvent(
        ToolUse(id="toolu_A", name="assistant__search_memory", input={"question": "matin"})
    )
    # JSON illisible : appel sans argument, que la validation par schema refusera ensuite.
    assert events[2] == ToolUseEvent(ToolUse(id="toolu_B", name="assistant__remember", input={}))
    completion = events[-1]
    assert isinstance(completion, Completion) and completion.stop_reason == "tool_use"


async def test_tools_history_and_choice_are_sent_in_the_api_format() -> None:
    provider, seen = make_provider(streaming(HAPPY_STREAM))

    _ = [e async for e in provider.chat_stream("claude-haiku-5-5", TOOLS_REQUEST)]

    body = json.loads(seen[0].content)
    assert body["tools"] == [
        {
            "name": "assistant__search_memory",
            "description": "Cherche.",
            "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}},
        }
    ]
    assert body["tool_choice"] == {"type": "none"}
    assert body["messages"][1] == {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Je regarde."},
            {
                "type": "tool_use",
                "id": "toolu_0",
                "name": "assistant__search_memory",
                "input": {"question": "réviser"},
            },
        ],
    }
    assert body["messages"][2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_0",
                "content": '{"souvenirs": []}',
                "is_error": False,
            }
        ],
    }


async def test_no_tools_means_no_tool_fields() -> None:
    provider, seen = make_provider(streaming(HAPPY_STREAM))
    _ = [e async for e in provider.chat_stream("claude-haiku-5-5", REQUEST)]
    body = json.loads(seen[0].content)
    assert "tools" not in body and "tool_choice" not in body
