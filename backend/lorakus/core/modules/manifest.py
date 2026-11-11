"""Manifeste d'un module : sa carte d'identite, verifiee au demarrage (MODULE_SYSTEM.md §2).

Le manifeste grandit avec le Core : outils, jobs et profil de specialiste s'y ajoutent dans
les PR suivantes, toujours avec une valeur par defaut (un manifeste existant reste valide).
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any, Final, Literal, Self

from fastapi import APIRouter
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODULE_ID: Final = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
TABLE_PREFIX: Final = re.compile(r"^[a-z][a-z0-9]{1,9}_$")
DataClass = Literal["public", "personal", "sensitive"]
SignalKind = Literal["scheduled", "contextual", "proactive"]
HealthCheck = Callable[[], Awaitable[bool]]


class ManifestError(ValueError):
    """Manifeste invalide : le message dit quoi corriger."""


class Signal(BaseModel):
    """Signal qu'un module peut emettre (MODULE_SYSTEM.md §4)."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: SignalKind
    description: str = Field(min_length=1)


class DataDeclaration(BaseModel):
    """Tables possedees par le module et classe de chacune (MODULE_SYSTEM.md §6)."""

    model_config = ConfigDict(frozen=True)

    table_prefix: str = ""
    tables: list[str] = Field(default_factory=list[str])
    classes: dict[str, DataClass] = Field(default_factory=dict[str, DataClass])

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.tables and not TABLE_PREFIX.fullmatch(self.table_prefix):
            raise ManifestError(
                f"table_prefix '{self.table_prefix}' invalide : "
                "2 a 10 caracteres puis '_' (ex. acad_)"
            )
        for table in self.tables:
            if not table.startswith(self.table_prefix):
                raise ManifestError(f"table '{table}' sans le prefixe '{self.table_prefix}'")
            if table.startswith("core_"):
                raise ManifestError(f"table '{table}' : le prefixe core_ est reserve au Core")
        missing = sorted(set(self.tables) - self.classes.keys())
        if missing:
            raise ManifestError(f"classe de donnees manquante pour : {', '.join(missing)}")
        unknown = sorted(self.classes.keys() - set(self.tables))
        if unknown:
            raise ManifestError(f"classe declaree pour une table inconnue : {', '.join(unknown)}")
        return self


class FrontendEntry(BaseModel):
    """Place du module dans l'interface (P3)."""

    model_config = ConfigDict(frozen=True)

    route: str
    label: str
    icon: str


class ModuleManifest(BaseModel):
    """Contrat d'un module avec le Core."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    name: str = Field(min_length=1)
    version: str
    requires_core: str
    description: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list[str])
    permissions: list[str] = Field(default_factory=list[str])
    config_schema: type[BaseModel] | None = None
    events_produced: list[str] = Field(default_factory=list[str])
    events_consumed: list[str] = Field(default_factory=list[str])
    signals_produced: list[Signal] = Field(default_factory=list[Signal])
    api_router: APIRouter | None = None
    # Module Python de ses modeles SQLAlchemy (lu par Alembic pour alembic check).
    models: str | None = None
    # Label de la branche Alembic du module (= son id) ; obligatoire s'il a des tables.
    migrations: str | None = None
    data: DataDeclaration = Field(default_factory=DataDeclaration)
    frontend: FrontendEntry | None = None
    health: HealthCheck | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not MODULE_ID.fullmatch(value):
            raise ManifestError(
                f"id '{value}' invalide : minuscules, chiffres et _, 2 a 31 caracteres"
            )
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as error:
            raise ManifestError(f"version '{value}' invalide (SemVer attendu)") from error
        return value

    @field_validator("requires_core")
    @classmethod
    def _requires_core(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise ManifestError(f"requires_core '{value}' invalide (ex. '>=0.2,<1.0')") from error
        return value

    @model_validator(mode="after")
    def _names_belong_to_the_module(self) -> Self:
        prefix = f"{self.id}."
        for event in self.events_produced:
            if not event.startswith(prefix):
                raise ManifestError(f"evenement produit '{event}' : doit commencer par '{prefix}'")
        for signal in self.signals_produced:
            if not signal.name.startswith(prefix):
                raise ManifestError(f"signal '{signal.name}' : doit commencer par '{prefix}'")
        for permission in self.permissions:
            module, _, action = permission.partition(":")
            if module != self.id or not action:
                raise ManifestError(
                    f"permission '{permission}' : forme attendue '{self.id}:action'"
                )
        if self.id in self.depends_on:
            raise ManifestError("un module ne peut pas dependre de lui-meme")
        if self.data.tables and self.migrations != self.id:
            raise ManifestError(
                f"le module a des tables : migrations doit valoir '{self.id}' (branche Alembic)"
            )
        return self

    def validate_config(self, config: dict[str, Any] | None) -> dict[str, Any]:
        """Configuration validee par config_schema (ou vide si le module n'en a pas)."""
        if self.config_schema is None:
            if config:
                raise ManifestError(f"le module '{self.id}' n'a pas de configuration")
            return {}
        return self.config_schema.model_validate(config or {}).model_dump(mode="json")
