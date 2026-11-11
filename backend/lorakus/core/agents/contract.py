"""Contrat des specialistes (ADR 0026) : une question typee, un rapport court et type.

Le rapport est borne (3 phrases, ~300 tokens) : le Majordome (P3) en combinera plusieurs.
Les actions suggerees ne sont JAMAIS executees par le specialiste : elles passent par les
outils, donc par la confirmation de l'utilisateur.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lorakus.core.modules.manifest import DataClass

LlmUsage = Literal["none", "formulation", "analysis"]
ReportStatus = Literal["ok", "partial", "no_data", "timeout", "error"]
MAX_REPORT_CHARS: Final = 1500  # environ 300 tokens
_CLASS_RANK: Final = {"public": 0, "personal": 1, "sensitive": 2}
INTENT: Final = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1, max_length=80)
    value: str = Field(max_length=200)
    data_class: DataClass
    source: str = Field(min_length=1, max_length=120)
    measured: bool = Field(description="Vrai si mesure, faux si estime ou predit")


class Confidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)


class SuggestedAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict[str, Any])
    why: str = Field(min_length=1, max_length=200)


class SpecialistRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID
    intent: str
    params: dict[str, Any] = Field(default_factory=dict[str, Any])
    context: dict[str, Any] = Field(default_factory=dict[str, Any])
    deadline: datetime
    budget_tokens: int = Field(default=0, ge=0)


class SpecialistReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ReportStatus
    summary: str = Field(max_length=400)
    facts: list[Fact] = Field(default_factory=list[Fact], max_length=10)
    confidence: Confidence | None = None
    suggested_actions: list[SuggestedAction] = Field(
        default_factory=list[SuggestedAction], max_length=3
    )
    freshness: datetime | None = None
    cost_eur: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        sentences = [s for s in re.split(r"[.!?]+(?:\s|$)", self.summary.strip()) if s]
        if len(sentences) > 3:
            raise ValueError("resume : 3 phrases au plus")
        if self.status == "ok" and self.confidence is None:
            raise ValueError("un rapport 'ok' motive sa confiance")
        if len(self.model_dump_json()) > MAX_REPORT_CHARS:
            raise ValueError(f"rapport trop long (plus de {MAX_REPORT_CHARS} caracteres)")
        return self

    def exceeds(self, max_class: DataClass) -> bool:
        """Vrai si un fait est d'une classe plus sensible que celle autorisee."""
        return any(_CLASS_RANK[f.data_class] > _CLASS_RANK[max_class] for f in self.facts)


@dataclass(frozen=True)
class SpecialistContext:
    """Ce que le Core donne au specialiste pour travailler."""

    request: SpecialistRequest
    open_transaction: Callable[[], Any]  # transaction liee a l'utilisateur (RLS)


SpecialistHandler = Callable[[SpecialistContext], Awaitable[SpecialistReport]]


class SpecialistProfile(BaseModel):
    """Profil d'un specialiste, declare dans le manifeste de son module (ADR 0026)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    display_name: str = Field(min_length=1)
    intents: list[str] = Field(min_length=1)
    data_scopes: list[str] = Field(default_factory=list[str])
    max_report_class: DataClass = "personal"
    llm_usage: LlmUsage = "none"
    monthly_llm_budget_eur: float = Field(default=0, ge=0)
    timeout_s: float = Field(default=3.0, gt=0, le=30)
    actions: list[str] = Field(default_factory=list[str])
    limits: str = Field(min_length=1, description="Ce que le specialiste ne fait pas, en clair")
    handler: SpecialistHandler

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        for intent in self.intents:
            if not INTENT.fullmatch(intent):
                raise ValueError(f"intention invalide : {intent}")
        if self.llm_usage == "none" and self.monthly_llm_budget_eur > 0:
            raise ValueError("budget LLM sans usage LLM")
        if self.llm_usage != "none" and self.monthly_llm_budget_eur == 0:
            raise ValueError("usage LLM sans budget mensuel")
        return self
