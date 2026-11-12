"""Routage et prix : la configuration livree est valide, et les erreurs bloquent le demarrage."""

from decimal import Decimal
from typing import get_args

import pytest

from lorakus.ai.catalog import Catalog, CatalogError
from lorakus.ai.port import DataClass, Usage
from lorakus.core.modules.manifest import DataClass as CoreDataClass

ROUTING = """
[providers.anthropic]
max_data_class = "personal"
[tasks.chat]
chain = ["anthropic:claude-haiku-5-5"]
max_input_tokens = 50000
max_output_tokens = 1024
"""

PRICING = """
checked_on = 2026-11-12
[models."anthropic:claude-haiku-5-5"]
source = "test"
input = "0.10"
output = "0.50"
cache_read = "0.01"
cache_write = "0.125"
long_prompt_threshold = 100000
long_input = "0.50"
long_output = "2.50"
long_cache_read = "0.05"
long_cache_write = "0.625"
"""


def test_shipped_configuration_is_valid_and_prices_every_target() -> None:
    catalog = Catalog.load()

    for route in catalog.routing.tasks.values():
        for target in route.chain:
            assert catalog.price(target).source
    # Les conversations (classe personal) ne partent que chez un fournisseur payant.
    assert catalog.policy("anthropic").max_data_class == "personal"
    # Toujours sous le palier long de Haiku 5.5, pour ne jamais payer le tarif superieur.
    assert catalog.route("chat").max_input_tokens < 100_000


def test_data_class_matches_the_core_definition() -> None:
    assert set(get_args(DataClass)) == set(get_args(CoreDataClass))


def test_cost_of_a_typical_message() -> None:
    price = Catalog.from_toml(ROUTING, PRICING).price("anthropic:claude-haiku-5-5")

    cost = price.cost(Usage(input_tokens=3000, output_tokens=400))

    # 3000 x 0,10 + 400 x 0,50, par million : 0,0005 $ exactement.
    assert cost == Decimal("0.0005")


def test_cost_counts_cache_tokens_at_their_own_rate() -> None:
    price = Catalog.from_toml(ROUTING, PRICING).price("anthropic:claude-haiku-5-5")

    cost = price.cost(
        Usage(input_tokens=0, output_tokens=0, cache_read_tokens=40_000, cache_write_tokens=8_000)
    )

    # 40 000 x 0,01 + 8 000 x 0,125, par million (sous le seuil : palier normal).
    assert cost == Decimal("0.0014")


def test_long_prompt_switches_the_whole_request_to_the_higher_tier() -> None:
    price = Catalog.from_toml(ROUTING, PRICING).price("anthropic:claude-haiku-5-5")

    at_threshold = price.cost(Usage(input_tokens=100_000, output_tokens=1000))
    above = price.cost(Usage(input_tokens=100_001, output_tokens=1000))

    assert at_threshold == Decimal("0.0105")  # 100 000 x 0,10 + 1000 x 0,50
    assert above == Decimal("0.0525005")  # 100 001 x 0,50 + 1000 x 2,50


@pytest.mark.parametrize(
    ("routing", "pricing", "message"),
    [
        (ROUTING.replace('"anthropic:', '"inconnu:'), PRICING, "fournisseur inconnu"),
        (ROUTING, PRICING.replace("anthropic:claude-haiku-5-5", "autre:modele"), "aucun prix"),
        (ROUTING, PRICING.replace('long_output = "2.50"\n', ""), "palier long incomplet"),
        (ROUTING.replace("anthropic:claude-haiku-5-5", "sans-deux-points"), PRICING, "cible"),
        (ROUTING.replace('"personal"', '"secret"'), PRICING, "max_data_class"),
        (ROUTING.replace("50000", "150000"), PRICING, "max_input_tokens"),
        (ROUTING + "inconnue = 1\n", PRICING, "inconnue"),
        ("pas du toml [", PRICING, "configuration IA invalide"),
    ],
)
def test_invalid_configuration_is_refused(routing: str, pricing: str, message: str) -> None:
    with pytest.raises(CatalogError, match=message):
        Catalog.from_toml(routing, pricing)


def test_unknown_task_is_an_error() -> None:
    with pytest.raises(CatalogError, match="inconnue"):
        Catalog.from_toml(ROUTING, PRICING).route("divination")
