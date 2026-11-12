"""ModelRouter : regles appliquees avant tout appel, repli, budget, disjoncteur, couts."""

import uuid
from decimal import Decimal

import pytest

from lorakus.ai.breaker import CircuitBreaker
from lorakus.ai.catalog import Catalog
from lorakus.ai.port import (
    AIProvider,
    ChatMessage,
    ChatRequest,
    DataClass,
    ProviderError,
    TextDelta,
    Usage,
)
from lorakus.ai.router import (
    AIInterruptedError,
    AIRefusedError,
    AIUnavailableError,
    ChatResult,
    ModelRouter,
    RouterEvent,
)
from lorakus.ai.testing import FakeProvider
from lorakus.observability.metrics import AI_REFUSALS

pytestmark = pytest.mark.anyio

USER = uuid.uuid4()

ROUTING = """
[providers.primary]
max_data_class = "personal"
[providers.backup]
max_data_class = "personal"
[providers.local]
max_data_class = "sensitive"
[tasks.chat]
chain = ["primary:m1", "backup:m2"]
max_input_tokens = 1000
max_output_tokens = 300
[tasks.private]
chain = ["primary:m1", "local:m3"]
max_input_tokens = 1000
max_output_tokens = 300
"""

PRICING = """
checked_on = 2026-11-12
[models."primary:m1"]
source = "test"
input = "1"
output = "2"
cache_read = "0"
cache_write = "0"
[models."backup:m2"]
source = "test"
input = "10"
output = "20"
cache_read = "0"
cache_write = "0"
[models."local:m3"]
source = "test"
input = "0"
output = "0"
cache_read = "0"
cache_write = "0"
"""


class MemoryLedger:
    """Journal de consommation en memoire (la version PostgreSQL a ses propres tests)."""

    def __init__(self, spent: str = "0", fail: bool = False) -> None:
        self.spent = Decimal(spent)
        self.fail = fail
        self.records: list[dict[str, object]] = []

    async def month_cost(self, user_id: uuid.UUID) -> Decimal:
        return self.spent

    async def record(self, user_id: uuid.UUID, **values: object) -> None:
        if self.fail:
            raise RuntimeError("base indisponible")
        self.records.append({"user_id": user_id, **values})


def request(text: str = "Bonjour", max_output_tokens: int = 1024) -> ChatRequest:
    return ChatRequest(
        system="Tu es Lorakus.",
        messages=[ChatMessage(role="user", content=text)],
        max_output_tokens=max_output_tokens,
    )


def make_router(
    providers: dict[str, AIProvider],
    ledger: MemoryLedger | None = None,
    *,
    budget: str = "3",
    kill_switch: bool = False,
    breaker: CircuitBreaker | None = None,
    quota: "CountingQuota | None" = None,
    max_concurrent: int | None = None,
) -> ModelRouter:
    return ModelRouter(
        Catalog.from_toml(ROUTING, PRICING),
        providers,
        ledger or MemoryLedger(),
        monthly_budget_usd=Decimal(budget),
        kill_switch=kill_switch,
        breaker=breaker,
        quota=quota,
        max_concurrent_per_user=max_concurrent,
    )


class CountingQuota:
    """Quota en memoire : `allowed` appels, puis refus (la version PostgreSQL est testee a part)."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.asked: list[uuid.UUID] = []

    async def allow(self, user_id: uuid.UUID) -> bool:
        self.asked.append(user_id)
        return len(self.asked) <= self.allowed


async def collect(
    router: ModelRouter,
    *,
    task: str = "chat",
    data_class: DataClass = "personal",
    req: ChatRequest | None = None,
    no_ai: bool = False,
) -> list[RouterEvent]:
    return [
        event
        async for event in router.chat_stream(
            USER, task=task, data_class=data_class, request=req or request(), no_ai=no_ai
        )
    ]


def text_of(events: list[RouterEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def result_of(events: list[RouterEvent]) -> ChatResult:
    last = events[-1]
    assert isinstance(last, ChatResult)
    return last


def external(replies: list[str] | None = None, **kwargs: object) -> FakeProvider:
    return FakeProvider(replies=replies or [], external=True, **kwargs)  # type: ignore[arg-type]


async def test_streams_text_then_result_and_records_the_cost() -> None:
    ledger = MemoryLedger()
    router = make_router({"primary": external(["Salut Anas, que puis-je faire ?"])}, ledger)

    events = await collect(router)

    assert text_of(events) == "Salut Anas, que puis-je faire ?"
    result = result_of(events)
    assert (result.provider, result.model) == ("primary", "m1")
    expected = (
        Decimal(result.usage.input_tokens) * 1 + Decimal(result.usage.output_tokens) * 2
    ) / (Decimal(1_000_000))
    assert result.cost_usd == expected
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record["user_id"] == USER
    assert record["provider"] == "primary"
    assert record["data_class"] == "personal"
    assert record["cost_usd"] == expected


async def test_no_ai_data_is_refused_before_any_call() -> None:
    provider = external(["ne doit pas repondre"])
    router = make_router({"primary": provider})

    with pytest.raises(AIRefusedError) as refused:
        await collect(router, no_ai=True)

    assert refused.value.reason == "no_ai"
    assert provider.calls == []


async def test_sensitive_data_never_reaches_an_external_provider() -> None:
    provider = external(["ne doit pas repondre"])
    router = make_router({"primary": provider, "backup": external()})

    with pytest.raises(AIRefusedError) as refused:
        await collect(router, data_class="sensitive")

    assert refused.value.reason == "data_class"
    assert provider.calls == []


async def test_sensitive_data_is_refused_externally_even_if_the_config_allows_it() -> None:
    # La politique de "local" accepte sensitive ; s'il etait externe, le code refuserait.
    leaking = external(["fuite"])
    router = make_router({"local": leaking})

    with pytest.raises(AIRefusedError):
        await collect(router, task="private", data_class="sensitive")

    assert leaking.calls == []


async def test_sensitive_data_can_use_a_local_provider() -> None:
    primary = external()
    router = make_router({"primary": primary, "local": FakeProvider(replies=["local"])})

    events = await collect(router, task="private", data_class="sensitive")

    assert text_of(events) == "local"
    assert primary.calls == []


async def test_kill_switch_stops_every_call() -> None:
    provider = external(["non"])
    router = make_router({"primary": provider}, kill_switch=True)

    with pytest.raises(AIUnavailableError) as unavailable:
        await collect(router)

    assert unavailable.value.reason == "kill_switch"
    assert provider.calls == []


async def test_too_long_prompt_is_refused_before_paying() -> None:
    provider = external(["non"])
    router = make_router({"primary": provider})

    with pytest.raises(AIRefusedError) as refused:
        await collect(router, req=request("x" * 5000))

    assert refused.value.reason == "too_long"
    assert provider.calls == []


async def test_reached_budget_stops_calls() -> None:
    provider = external(["non"])
    router = make_router({"primary": provider}, MemoryLedger(spent="3.00"), budget="3")

    with pytest.raises(AIUnavailableError) as unavailable:
        await collect(router)

    assert unavailable.value.reason == "budget"
    assert provider.calls == []


async def test_budget_warning_from_eighty_percent() -> None:
    below = make_router({"primary": external(["ok"])}, MemoryLedger(spent="2.39"), budget="3")
    above = make_router({"primary": external(["ok"])}, MemoryLedger(spent="2.40"), budget="3")

    assert not result_of(await collect(below)).budget_warning
    assert result_of(await collect(above)).budget_warning


async def test_falls_back_when_the_first_provider_fails_before_answering() -> None:
    failing = external(fail_before=ProviderError("unavailable", "panne"))
    backup = external(["reponse de secours"])
    router = make_router({"primary": failing, "backup": backup})

    events = await collect(router)

    assert text_of(events) == "reponse de secours"
    assert result_of(events).provider == "backup"
    assert len(failing.calls) == 1


async def test_failure_after_first_text_is_reported_without_switching_model() -> None:
    ledger = MemoryLedger()
    broken = external(["un deux trois quatre"], fail_after_chunks=2)
    backup = external(["ne doit pas repondre"])
    router = make_router({"primary": broken, "backup": backup}, ledger)
    received: list[str] = []

    with pytest.raises(AIInterruptedError):
        async for event in router.chat_stream(
            USER, task="chat", data_class="personal", request=request()
        ):
            if isinstance(event, TextDelta):
                received.append(event.text)

    assert "".join(received) == "un deux"
    assert backup.calls == []
    assert ledger.records == []


async def test_all_providers_down_means_unavailable() -> None:
    router = make_router(
        {
            "primary": external(fail_before=ProviderError("unavailable", "panne")),
            "backup": external(fail_before=ProviderError("rate_limited", "limite")),
        }
    )

    with pytest.raises(AIUnavailableError) as unavailable:
        await collect(router)

    assert unavailable.value.reason == "no_provider"


async def test_no_configured_provider_means_unavailable() -> None:
    router = make_router({})

    with pytest.raises(AIUnavailableError) as unavailable:
        await collect(router)

    assert unavailable.value.reason == "no_provider"


async def test_open_circuit_skips_the_failing_provider_without_waiting() -> None:
    failing = external(fail_before=ProviderError("unavailable", "panne"))
    backup = external(["a", "b", "c", "d"])
    router = make_router(
        {"primary": failing, "backup": backup}, breaker=CircuitBreaker(threshold=3, cooldown_s=60)
    )

    for _ in range(4):
        await collect(router)

    assert len(failing.calls) == 3  # le quatrieme message ne l'attend plus
    assert len(backup.calls) == 4


async def test_output_length_is_capped_by_the_task() -> None:
    provider = external(["ok"])
    router = make_router({"primary": provider})

    await collect(router, req=request(max_output_tokens=4000))

    assert provider.calls[0][1].max_output_tokens == 300


async def test_usage_write_failure_does_not_break_the_answer() -> None:
    router = make_router({"primary": external(["ok"])}, MemoryLedger(fail=True))

    events = await collect(router)

    assert text_of(events) == "ok"


async def test_client_leaving_mid_answer_does_not_jam_the_circuit() -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_s=0)
    breaker.failure("primary")  # circuit ouvert, la prochaine requete est un essai
    router = make_router({"primary": external(["un deux trois", "encore"])}, breaker=breaker)

    stream = router.chat_stream(USER, task="chat", data_class="personal", request=request())
    await anext(stream)
    await stream.aclose()  # l'utilisateur ferme l'application pendant la reponse

    assert breaker.allows("primary")


async def test_refusals_are_counted() -> None:
    counter = AI_REFUSALS.labels(task="chat", reason="kill_switch")
    before = counter._value.get()  # pyright: ignore[reportPrivateUsage]
    router = make_router({"primary": external()}, kill_switch=True)

    with pytest.raises(AIUnavailableError):
        await collect(router)

    assert counter._value.get() == before + 1  # pyright: ignore[reportPrivateUsage]


async def test_call_quota_stops_a_burst_before_paying() -> None:
    provider = external(["un", "deux", "trois"])
    quota = CountingQuota(allowed=2)
    router = make_router({"primary": provider}, quota=quota)

    await collect(router)
    await collect(router)
    with pytest.raises(AIUnavailableError) as unavailable:
        await collect(router)

    assert unavailable.value.reason == "rate_limited"
    assert len(provider.calls) == 2
    assert quota.asked == [USER, USER, USER]


async def test_quota_is_not_consumed_when_the_budget_is_already_reached() -> None:
    quota = CountingQuota(allowed=10)
    router = make_router(
        {"primary": external(["non"])}, MemoryLedger(spent="3"), budget="3", quota=quota
    )

    with pytest.raises(AIUnavailableError):
        await collect(router)

    assert quota.asked == []


async def test_concurrent_answers_per_user_are_capped_and_released() -> None:
    quota = CountingQuota(allowed=10)
    router = make_router(
        {"primary": external(["un deux", "trois", "quatre"])}, quota=quota, max_concurrent=1
    )
    first = router.chat_stream(USER, task="chat", data_class="personal", request=request())
    await anext(first)  # une reponse en cours

    with pytest.raises(AIUnavailableError) as busy:
        await collect(router)
    assert busy.value.reason == "rate_limited"
    assert len(quota.asked) == 1  # le refus pour reponse en cours ne consomme pas le quota

    other = uuid.uuid4()  # un autre utilisateur n'est pas gene
    events = [
        e
        async for e in router.chat_stream(
            other, task="chat", data_class="personal", request=request()
        )
    ]
    assert text_of(events) == "trois"

    await first.aclose()  # le client part : la place se libere
    assert text_of(await collect(router)) == "quatre"


def test_usage_prompt_tokens_include_cache() -> None:
    assert Usage(input_tokens=1, cache_read_tokens=2, cache_write_tokens=3).prompt_tokens == 6
