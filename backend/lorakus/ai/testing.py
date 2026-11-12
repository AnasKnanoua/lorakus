"""Faux fournisseur d'IA : tests, evals et developpement sans cle (jamais en production).

Il repond mot par mot, comme un vrai flux, avec des reponses scriptees ou un echo du
dernier message ; il peut aussi simuler une panne avant ou pendant la reponse.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from lorakus.ai.port import (
    Capabilities,
    ChatRequest,
    Completion,
    ProviderError,
    StreamEvent,
    TextDelta,
    Usage,
    estimate_tokens,
)

DEV_PREFIX = "Mode developpement, aucun modele configure. Vous avez ecrit : "


@dataclass
class FakeProvider:
    replies: list[str] = field(default_factory=list[str])
    fail_before: ProviderError | None = None
    fail_after_chunks: int | None = None
    external: bool = False
    delay_s: float = 0.0
    provider_name: str = "fake"
    calls: list[tuple[str, ChatRequest]] = field(default_factory=list[tuple[str, ChatRequest]])

    @property
    def name(self) -> str:
        return self.provider_name

    def capabilities(self) -> Capabilities:
        return Capabilities(external=self.external)

    def _reply(self, request: ChatRequest) -> str:
        if self.replies:
            return self.replies.pop(0)
        return DEV_PREFIX + request.messages[-1].content

    async def chat_stream(self, model: str, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append((model, request))
        if self.fail_before is not None:
            raise self.fail_before
        reply = self._reply(request)
        words = reply.split(" ")
        for index, word in enumerate(words):
            if self.fail_after_chunks is not None and index >= self.fail_after_chunks:
                raise ProviderError("unavailable", "panne simulee en cours de reponse")
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield TextDelta(word if index == 0 else " " + word)
        prompt = request.system + "".join(m.content for m in request.messages)
        yield Completion(
            usage=Usage(input_tokens=estimate_tokens(prompt), output_tokens=estimate_tokens(reply)),
            stop_reason="end_turn",
        )
