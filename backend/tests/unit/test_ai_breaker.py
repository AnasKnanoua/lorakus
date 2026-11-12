"""Disjoncteur : on cesse d'attendre un fournisseur en panne, puis on reessaie une fois."""

from lorakus.ai.breaker import CircuitBreaker


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_opens_after_consecutive_failures_and_probes_once_after_cooldown() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=3, cooldown_s=120, clock=clock)

    for _ in range(2):
        breaker.failure("p")
    assert breaker.allows("p")
    breaker.failure("p")
    assert not breaker.allows("p")

    clock.now = 119
    assert not breaker.allows("p")
    clock.now = 120
    assert breaker.allows("p")  # une requete d'essai...
    assert not breaker.allows("p")  # ...et une seule


def test_successful_probe_closes_the_circuit() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=10, clock=clock)
    breaker.failure("p")
    clock.now = 10
    assert breaker.allows("p")

    breaker.success("p")

    assert breaker.allows("p")
    assert not breaker.is_open("p")


def test_failed_probe_reopens_for_a_full_cooldown() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=3, cooldown_s=10, clock=clock)
    for _ in range(3):
        breaker.failure("p")
    clock.now = 10
    assert breaker.allows("p")

    breaker.failure("p")

    clock.now = 19
    assert not breaker.allows("p")
    clock.now = 20
    assert breaker.allows("p")


def test_abandoned_probe_does_not_block_the_provider_forever() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=10, clock=clock)
    breaker.failure("p")
    clock.now = 10
    assert breaker.allows("p")

    breaker.abandoned("p")  # l'utilisateur a ferme l'application pendant l'essai

    assert breaker.allows("p")


def test_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.failure("p")
    breaker.success("p")
    breaker.failure("p")

    assert breaker.allows("p")


def test_providers_are_independent() -> None:
    breaker = CircuitBreaker(threshold=1)
    breaker.failure("a")

    assert not breaker.allows("a")
    assert breaker.allows("b")
