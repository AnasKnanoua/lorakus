"""Orchestrateur et routage des specialistes (PR 39), sans base de donnees.

Le faux annuaire simule des specialistes rapides, lents, en panne ou mis en cache ; une
horloge manipulable fait avancer le temps du disjoncteur et du cache sans attendre.
"""

import asyncio
import time
import uuid
from typing import Any

import pytest

from lorakus.ai.embeddings import FakeEmbedder
from lorakus.core.agents.contract import (
    Confidence,
    Fact,
    SpecialistContext,
    SpecialistProfile,
    SpecialistReport,
)
from lorakus.core.agents.orchestrator import (
    BREAKER_COOLDOWN_S,
    MAX_PARALLEL,
    Orchestrator,
    Target,
)
from lorakus.core.agents.routing import NONE, IntentRouter, fold
from lorakus.core.agents.service import Answer, classes_for_llm, llm_eligible

pytestmark = pytest.mark.anyio
USER = uuid.uuid4()


async def _noop(_ctx: SpecialistContext) -> SpecialistReport:
    return SpecialistReport(status="no_data", summary="Rien.")


def profile(name: str, **extra: Any) -> SpecialistProfile:
    values: dict[str, Any] = {
        "name": name,
        "display_name": name.capitalize(),
        "intents": ["main"],
        "limits": "Fictif.",
        "handler": _noop,
    }
    values.update(extra)
    return SpecialistProfile(**values)


def ok(summary: str = "Tout va bien.", facts: list[Fact] | None = None) -> SpecialistReport:
    return SpecialistReport(
        status="ok",
        summary=summary,
        facts=facts or [],
        confidence=Confidence(level=0.9, reason="test"),
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeDirectory:
    """Annuaire factice : `behaviours[nom]` = (delai en s, rapport ou exception)."""

    def __init__(self, profiles: list[SpecialistProfile]) -> None:
        self.profiles = {p.name: p for p in profiles}
        self.behaviours: dict[str, tuple[float, SpecialistReport | Exception]] = {}
        self.calls: list[tuple[str, float | None, str | None]] = []

    def profile(self, name: str) -> SpecialistProfile | None:
        return self.profiles.get(name)

    async def available(self, user_id: uuid.UUID) -> list[SpecialistProfile]:
        return list(self.profiles.values())

    async def ask(
        self,
        user_id: uuid.UUID,
        name: str,
        intent: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_s: float | None = None,
        trace_id: str | None = None,
        for_llm: bool = False,
    ) -> Answer:
        self.calls.append((name, timeout_s, trace_id))
        delay, outcome = self.behaviours.get(name, (0.0, ok()))
        if isinstance(outcome, Exception):
            raise outcome
        # Comme AgentService.ask : delai depasse -> rapport "timeout".
        if timeout_s is not None and delay > timeout_s:
            await asyncio.sleep(timeout_s)
            return Answer(name, SpecialistReport(status="timeout", summary="Trop lent."), 0)
        await asyncio.sleep(delay)
        return Answer(name, outcome, int(delay * 1000))


# ------------------------------------------------------------------ orchestrateur
async def test_specialists_are_consulted_in_parallel_under_a_global_deadline() -> None:
    directory = FakeDirectory([profile("a"), profile("b"), profile("slow")])
    directory.behaviours = {"a": (0.3, ok()), "b": (0.3, ok()), "slow": (10.0, ok())}
    orchestrator = Orchestrator(directory)

    started = time.monotonic()
    results = await orchestrator.consult(
        USER, [Target("a", "main"), Target("b", "main"), Target("slow", "main")], deadline_s=0.6
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.9  # en parallele : ni 0,3 + 0,3, ni 10 s
    assert [r.report.status for r in results] == ["ok", "ok", "timeout"]
    assert all(call[1] is not None and call[1] <= 0.6 for call in directory.calls)


async def test_at_most_four_specialists_and_the_trace_id_is_passed() -> None:
    names = [f"s{i}" for i in range(6)]
    directory = FakeDirectory([profile(n) for n in names])
    results = await Orchestrator(directory).consult(
        USER, [Target(n, "main") for n in names], trace_id="reponse-1"
    )
    assert len(results) == MAX_PARALLEL
    assert {call[2] for call in directory.calls} == {"reponse-1"}


async def test_breaker_skips_a_failing_specialist_then_lets_it_try_again() -> None:
    clock = Clock()
    directory = FakeDirectory([profile("flaky")])
    directory.behaviours = {"flaky": (0.0, SpecialistReport(status="error", summary="Panne."))}
    orchestrator = Orchestrator(directory, clock=clock)
    target = [Target("flaky", "main")]

    for _ in range(3):
        await orchestrator.consult(USER, target)
    skipped = await orchestrator.consult(USER, target)
    assert skipped[0].skipped == "breaker"
    assert len(directory.calls) == 3  # le 4e n'a pas ete appele

    clock.now += BREAKER_COOLDOWN_S
    directory.behaviours = {"flaky": (0.0, ok())}
    retried = await orchestrator.consult(USER, target)
    assert retried[0].report.status == "ok" and retried[0].skipped is None


async def test_cache_serves_a_report_until_it_expires_and_never_across_users() -> None:
    clock = Clock()
    directory = FakeDirectory([profile("cached", cache_ttl_s=60)])
    orchestrator = Orchestrator(directory, clock=clock)
    target = [Target("cached", "main")]

    first = await orchestrator.consult(USER, target)
    second = await orchestrator.consult(USER, target)
    assert not first[0].cached and second[0].cached
    assert len(directory.calls) == 1
    await orchestrator.consult(uuid.uuid4(), target)  # autre utilisateur : pas de partage
    assert len(directory.calls) == 2
    clock.now += 61
    third = await orchestrator.consult(USER, target)
    assert not third[0].cached and len(directory.calls) == 3


async def test_no_cache_by_default_and_failures_are_never_cached() -> None:
    directory = FakeDirectory([profile("plain"), profile("bad", cache_ttl_s=60)])
    directory.behaviours["bad"] = (0.0, SpecialistReport(status="error", summary="Panne."))
    orchestrator = Orchestrator(directory)
    for _ in range(2):
        await orchestrator.consult(USER, [Target("plain", "main"), Target("bad", "main")])
    assert [c[0] for c in directory.calls].count("plain") == 2
    assert [c[0] for c in directory.calls].count("bad") == 2


async def test_sensitive_specialists_never_send_anything_to_the_model() -> None:
    secret = Fact(
        label="solde", value="1200", data_class="sensitive", source="banque", measured=True
    )
    plain = Fact(label="cours", value="3", data_class="personal", source="agenda", measured=True)
    bank = profile("bank", max_report_class="sensitive")
    focus = profile("focus")
    assert not llm_eligible(bank) and llm_eligible(focus)
    assert classes_for_llm(bank, ok(facts=[secret])) == []
    assert classes_for_llm(focus, ok(facts=[plain])) == ["personal"]
    assert classes_for_llm(focus, SpecialistReport(status="timeout", summary="x")) == []


# ---------------------------------------------------------------------- routage
DAY = profile(
    "focus",
    intents=["day_plan", "deadlines"],
    keywords={"day_plan": ["aujourd'hui", "programme"], "deadlines": ["devoir", "échéance"]},
    examples={"day_plan": ["programme planning journee taches"]},
)
SLEEP = profile(
    "fitness",
    intents=["sleep"],
    keywords={"sleep": ["dormi", "sommeil"]},
    examples={"sleep": ["nuit sommeil dormir repos"]},
)


async def test_rules_can_select_several_specialists() -> None:
    routing = await IntentRouter().route(
        "Mon programme d'aujourd'hui, et j'ai bien dormi ?", [DAY, SLEEP]
    )
    assert routing.tier == "rules"
    assert [(t.specialist, t.intent) for t in routing.targets] == [
        ("focus", "day_plan"),
        ("fitness", "sleep"),
    ]


async def test_rules_match_whole_words_without_accents() -> None:
    assert fold("Échéance du DEVOIR !") == "echeance du devoir"
    router = IntentRouter()
    assert (await router.route("Une echeance ?", [DAY])).targets == (Target("focus", "deadlines"),)
    # « devoirs » contient « devoir » mais n'est pas le mot exact : pas de regle.
    assert (await router.route("redevoirable", [DAY])).tier == "none"


async def test_meaning_picks_a_clear_winner_and_refuses_ambiguity() -> None:
    router = IntentRouter(FakeEmbedder(), margin=0.05)
    clear = await router.route("planning taches journee", [DAY, SLEEP])
    assert clear.tier == "embeddings"
    assert clear.targets == (Target("focus", "day_plan"),)
    assert clear.score is not None and clear.runner_up is not None
    assert clear.score - clear.runner_up >= 0.05

    strict = IntentRouter(FakeEmbedder(), margin=0.99)
    ambiguous = await strict.route("planning taches journee", [DAY, SLEEP])
    assert ambiguous.targets == () and ambiguous.reason == "ambigu"


async def test_default_margin_comes_from_the_tuning_set() -> None:
    """0 : choisie sur la partie `tuning` du jeu d'evaluation avec le vrai modele (CI)."""
    from lorakus.core.agents.routing import DEFAULT_MARGIN

    assert DEFAULT_MARGIN == 0.0


async def test_off_topic_questions_consult_nobody() -> None:
    routing = await IntentRouter(FakeEmbedder()).route("Merci beaucoup", [DAY, SLEEP])
    assert routing.targets == () and routing.best == NONE


async def test_without_profiles_nothing_is_computed() -> None:
    embedder = FakeEmbedder()
    routing = await IntentRouter(embedder).route("Mon programme ?", [])
    assert routing.targets == () and embedder.calls == []


async def test_embedding_failure_consults_nobody() -> None:
    embedder = FakeEmbedder()
    embedder.fail = True
    routing = await IntentRouter(embedder).route("planning taches journee", [DAY, SLEEP])
    assert routing.targets == () and "indisponible" in routing.reason


async def test_example_vectors_are_computed_once() -> None:
    embedder = FakeEmbedder()
    router = IntentRouter(embedder)
    await router.route("planning", [DAY, SLEEP])
    first = len(embedder.calls)
    await router.route("repos de la nuit", [DAY, SLEEP])  # aucun mot-cle : palier 2
    assert len(embedder.calls) == first + 1  # seule la nouvelle question est calculee


def test_profiles_reject_routing_for_unknown_intents() -> None:
    with pytest.raises(ValueError, match="intention non declaree"):
        profile("x", keywords={"other": ["mot"]})
    with pytest.raises(ValueError, match="phrases non vides"):
        profile("x", examples={"main": []})
