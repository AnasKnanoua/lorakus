"""Contrat des specialistes et coherence des manifestes (outils, intentions)."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from lorakus.core.agents.contract import Confidence, SpecialistProfile, SpecialistReport
from lorakus.core.modules.manifest import DataDeclaration, ModuleManifest
from lorakus.core.modules.registry import ModuleRegistry, ModuleRegistryError
from lorakus.core.tools.spec import ToolCall, ToolSpec


class Empty(BaseModel):
    pass


async def _tool(_call: ToolCall, _args: Empty) -> dict[str, Any]:
    return {}


async def _handler(_ctx: Any) -> SpecialistReport:
    return SpecialistReport(status="no_data", summary="Rien.")


def _profile(name: str, **extra: Any) -> SpecialistProfile:
    fields: dict[str, Any] = {
        "display_name": name,
        "intents": [f"{name}_intent"],
        "limits": "x",
        "handler": _handler,
    }
    fields.update(extra)
    return SpecialistProfile(name=name, **fields)


def _module(module_id: str, **extra: Any) -> ModuleManifest:
    return ModuleManifest(
        id=module_id,
        name=module_id,
        version="0.1.0",
        requires_core=">=0.1",
        description="x",
        **extra,
    )


def test_report_is_short_and_ok_reports_explain_their_confidence() -> None:
    with pytest.raises(ValidationError, match="3 phrases"):
        SpecialistReport(status="no_data", summary="Un. Deux. Trois. Quatre.")
    with pytest.raises(ValidationError, match="motive sa confiance"):
        SpecialistReport(status="ok", summary="Fait.")
    SpecialistReport(
        status="ok", summary="Fait.", confidence=Confidence(level=0.5, reason="peu de donnees")
    )


def test_profile_rules() -> None:
    with pytest.raises(ValidationError, match="budget LLM sans usage"):
        _profile("a", monthly_llm_budget_eur=2)
    with pytest.raises(ValidationError, match="usage LLM sans budget"):
        _profile("a", llm_usage="analysis")
    with pytest.raises(ValidationError, match="intention invalide"):
        _profile("a", intents=["Pas Bien"])


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"tools": [ToolSpec("other.xyz", "x", "read", Empty, _tool)]}, "outil 'other.xyz'"),
        ({"specialist": _profile("other")}, "doit porter l'id du module"),
        (
            {"specialist": _profile("alpha", data_scopes=["al_x"]), "data": DataDeclaration()},
            "data_scopes hors du module",
        ),
        ({"specialist": _profile("alpha", actions=["alpha.do_it"])}, "sans outil declare"),
    ],
)
def test_manifest_checks_tools_and_specialist(extra: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _module("alpha", **extra)


def test_intents_are_unique_across_specialists() -> None:
    with pytest.raises(ModuleRegistryError, match="revendiquee"):
        ModuleRegistry(
            [
                _module("alpha", specialist=_profile("alpha", intents=["same"])),
                _module("beta", specialist=_profile("beta", intents=["same"])),
            ],
            core_version="0.2.0",
        )


def test_tool_names_are_checked() -> None:
    with pytest.raises(ValueError, match="nom d'outil invalide"):
        ToolSpec("pas_de_point", "x", "read", Empty, _tool)
