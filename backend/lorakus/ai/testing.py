"""Faux fournisseur d'IA : tests, evals et developpement sans cle (jamais en production).

Il repond mot par mot, comme un vrai flux, avec des reponses scriptees ou un echo du
dernier message ; il peut aussi simuler une panne avant ou pendant la reponse.

Une reponse scriptee peut etre un texte, ou une FakeReply qui ajoute des demandes d'appel
d'outils apres le texte (PR 38) : c'est ainsi que les tests rejouent un modele qui utilise
des outils, ou qui tente d'en abuser.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from lorakus.ai.port import (
    Capabilities,
    ChatRequest,
    Completion,
    ProviderError,
    StreamEvent,
    TextDelta,
    ToolUse,
    ToolUseEvent,
    Usage,
    estimate_tokens,
    request_tokens,
)

DEV_PREFIX = "Mode developpement, aucun modele configure. Vous avez ecrit : "


@dataclass(frozen=True)
class FakeReply:
    """Reponse scriptee : du texte (peut etre vide), puis des appels (nom fil, arguments)."""

    text: str = ""
    tool_calls: tuple[tuple[str, dict[str, Any]], ...] = ()


@dataclass
class FakeProvider:
    replies: list[str | FakeReply] = field(default_factory=list[str | FakeReply])
    fail_before: ProviderError | None = None
    fail_after_chunks: int | None = None
    external: bool = False
    tools: bool = True
    delay_s: float = 0.0
    provider_name: str = "fake"
    calls: list[tuple[str, ChatRequest]] = field(default_factory=list[tuple[str, ChatRequest]])

    @property
    def name(self) -> str:
        return self.provider_name

    def capabilities(self) -> Capabilities:
        return Capabilities(external=self.external, tools=self.tools)

    def _reply(self, request: ChatRequest) -> str:
        """Texte de la prochaine reponse (les tests peuvent le redefinir)."""
        if self.replies and isinstance(self.replies[0], str):
            return str(self.replies.pop(0))
        last = request.messages[-1]
        return DEV_PREFIX + (last.content or "(resultat d'outil)")

    def _next(self, request: ChatRequest) -> FakeReply:
        if self.replies and isinstance(self.replies[0], FakeReply):
            scripted = self.replies.pop(0)
            if isinstance(scripted, FakeReply):
                return scripted
        return FakeReply(text=self._reply(request))

    async def chat_stream(self, model: str, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append((model, request))
        if self.fail_before is not None:
            raise self.fail_before
        reply = self._next(request)
        words = reply.text.split(" ") if reply.text else []
        for index, word in enumerate(words):
            if self.fail_after_chunks is not None and index >= self.fail_after_chunks:
                raise ProviderError("unavailable", "panne simulee en cours de reponse")
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield TextDelta(word if index == 0 else " " + word)
        calls = reply.tool_calls if request.tool_choice == "auto" else ()
        for number, (name, arguments) in enumerate(calls, start=1):
            yield ToolUseEvent(
                ToolUse(id=f"toolu_{len(self.calls)}_{number}", name=name, input=arguments)
            )
        yield Completion(
            usage=Usage(
                input_tokens=request_tokens(request), output_tokens=estimate_tokens(reply.text)
            ),
            stop_reason="tool_use" if calls else "end_turn",
        )
