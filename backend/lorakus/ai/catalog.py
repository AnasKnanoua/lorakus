"""Routage et prix des modeles, lus depuis config/routing.toml et config/pricing.toml.

Tout est verifie au chargement, donc au demarrage de l'API : une cible sans prix, un
fournisseur inconnu ou un fournisseur externe autorise a recevoir `sensitive` empechent
l'application de demarrer, au lieu de produire une facture ou une fuite plus tard.
"""

import re
import tomllib
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lorakus.ai.port import DataClass, Usage

PER_MILLION: Final = Decimal(1_000_000)
_TARGET_PATTERN: Final = r"^[a-z][a-z0-9_]*:[a-z0-9][a-z0-9._-]*$"


class CatalogError(ValueError):
    """Configuration du routage ou des prix invalide."""


def split_target(target: str) -> tuple[str, str]:
    """`anthropic:claude-haiku-5-5` -> (`anthropic`, `claude-haiku-5-5`)."""
    provider, model = target.split(":", 1)
    return provider, model


class ProviderPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_data_class: DataClass


class TaskRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chain: list[str] = Field(min_length=1)
    max_input_tokens: int = Field(ge=100, le=90_000)
    max_output_tokens: int = Field(ge=1, le=8192)

    @model_validator(mode="after")
    def _targets(self) -> Self:
        for target in self.chain:
            if not re.fullmatch(_TARGET_PATTERN, target):
                raise ValueError(f"cible invalide : {target!r} (attendu fournisseur:modele)")
        if len(set(self.chain)) != len(self.chain):
            raise ValueError("cible en double dans la chaine")
        return self


class Routing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: dict[str, ProviderPolicy]
    tasks: dict[str, TaskRoute] = Field(min_length=1)


class Price(BaseModel):
    """Prix d'un modele en dollars par million de tokens, avec un palier long facultatif."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_read: Decimal = Field(ge=0)
    cache_write: Decimal = Field(ge=0)
    long_prompt_threshold: int | None = Field(default=None, ge=1)
    long_input: Decimal | None = Field(default=None, ge=0)
    long_output: Decimal | None = Field(default=None, ge=0)
    long_cache_read: Decimal | None = Field(default=None, ge=0)
    long_cache_write: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _long_tier_complete(self) -> Self:
        long_prices = (
            self.long_input,
            self.long_output,
            self.long_cache_read,
            self.long_cache_write,
        )
        given = [p is not None for p in long_prices]
        if self.long_prompt_threshold is not None and not all(given):
            raise ValueError("palier long incomplet : seuil et quatre prix long_* ensemble")
        if self.long_prompt_threshold is None and any(given):
            raise ValueError("palier long incomplet : seuil et quatre prix long_* ensemble")
        return self

    def cost(self, usage: Usage) -> Decimal:
        """Cout en dollars d'une requete (palier choisi selon la taille totale du prompt)."""
        long_tier = (
            self.long_prompt_threshold is not None
            and usage.prompt_tokens > self.long_prompt_threshold
        )
        if long_tier:
            # Valeurs garanties non nulles par _long_tier_complete.
            rates = (
                self.long_input or Decimal(0),
                self.long_output or Decimal(0),
                self.long_cache_read or Decimal(0),
                self.long_cache_write or Decimal(0),
            )
        else:
            rates = (self.input, self.output, self.cache_read, self.cache_write)
        tokens = (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
        total = sum((Decimal(n) * r for n, r in zip(tokens, rates, strict=True)), Decimal(0))
        return total / PER_MILLION


class Pricing(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checked_on: date
    models: dict[str, Price] = Field(min_length=1)


class Catalog(BaseModel):
    """Routage et prix, valides ensemble."""

    model_config = ConfigDict(frozen=True)

    routing: Routing
    pricing: Pricing

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        for name, route in self.routing.tasks.items():
            for target in route.chain:
                provider, _ = split_target(target)
                if provider not in self.routing.providers:
                    raise ValueError(f"tache {name} : fournisseur inconnu {provider!r}")
                if target not in self.pricing.models:
                    raise ValueError(f"tache {name} : aucun prix pour {target!r}")
        return self

    def route(self, task: str) -> TaskRoute:
        try:
            return self.routing.tasks[task]
        except KeyError:
            raise CatalogError(f"tache IA inconnue : {task!r}") from None

    def price(self, target: str) -> Price:
        return self.pricing.models[target]

    def policy(self, provider: str) -> ProviderPolicy:
        return self.routing.providers[provider]

    @classmethod
    def from_toml(cls, routing_toml: str, pricing_toml: str) -> Self:
        try:
            return cls(
                routing=Routing.model_validate(tomllib.loads(routing_toml)),
                pricing=Pricing.model_validate(tomllib.loads(pricing_toml)),
            )
        except (tomllib.TOMLDecodeError, ValueError) as error:
            raise CatalogError(f"configuration IA invalide : {error}") from error

    @classmethod
    def load(cls) -> Self:
        """Charge les fichiers livres avec le paquet (fonctionne aussi depuis une wheel)."""
        config = resources.files("lorakus.ai").joinpath("config")
        return cls.from_toml(
            config.joinpath("routing.toml").read_text(encoding="utf-8"),
            config.joinpath("pricing.toml").read_text(encoding="utf-8"),
        )
