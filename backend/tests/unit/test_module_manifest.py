"""Regles du manifeste et du registre des modules."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from lorakus.core.modules.manifest import DataDeclaration, ModuleManifest, Signal
from lorakus.core.modules.registry import ModuleRegistry, ModuleRegistryError


def make(module_id: str = "alpha", **overrides: Any) -> ModuleManifest:
    fields: dict[str, Any] = {
        "id": module_id,
        "name": module_id.capitalize(),
        "version": "0.1.0",
        "requires_core": ">=0.1,<1.0",
        "description": "Module de test",
    }
    fields.update(overrides)
    return ModuleManifest(**fields)


def test_minimal_manifest_is_valid() -> None:
    assert make().id == "alpha"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "Alpha"}, "id 'Alpha' invalide"),
        ({"version": "un"}, "SemVer"),
        ({"requires_core": "bientot"}, "requires_core"),
        ({"events_produced": ["beta.done"]}, "doit commencer par 'alpha.'"),
        (
            {"signals_produced": [Signal(name="x.y", kind="proactive", description="d")]},
            "signal 'x.y'",
        ),
        ({"permissions": ["beta:read"]}, "forme attendue 'alpha:action'"),
        ({"permissions": ["alpha"]}, "forme attendue"),
        ({"depends_on": ["alpha"]}, "lui-meme"),
        (
            {
                "data": DataDeclaration(
                    table_prefix="al_", tables=["al_x"], classes={"al_x": "personal"}
                )
            },
            "migrations doit valoir 'alpha'",
        ),
    ],
)
def test_invalid_manifests_are_refused(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make(**overrides)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {"table_prefix": "al", "tables": ["al_x"], "classes": {"al_x": "personal"}},
            "table_prefix",
        ),
        (
            {"table_prefix": "al_", "tables": ["other_x"], "classes": {"other_x": "personal"}},
            "sans le prefixe",
        ),
        (
            {"table_prefix": "core_", "tables": ["core_x"], "classes": {"core_x": "personal"}},
            "reserve au Core",
        ),
        ({"table_prefix": "al_", "tables": ["al_x"], "classes": {}}, "classe de donnees manquante"),
        (
            {
                "table_prefix": "al_",
                "tables": ["al_x"],
                "classes": {"al_x": "personal", "al_y": "public"},
            },
            "table inconnue",
        ),
    ],
)
def test_data_declaration_rules(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        DataDeclaration(**data)


def test_config_is_validated_by_its_schema() -> None:
    class Config(BaseModel):
        threshold: int = 3

    manifest = make(config_schema=Config)
    assert manifest.validate_config(None) == {"threshold": 3}
    assert manifest.validate_config({"threshold": 5}) == {"threshold": 5}
    with pytest.raises(ValidationError):
        manifest.validate_config({"threshold": "beaucoup"})
    with pytest.raises(ValueError, match="pas de configuration"):
        make().validate_config({"x": 1})


def test_registry_orders_dependencies_first() -> None:
    registry = ModuleRegistry(
        [make("gamma", depends_on=["beta"]), make("beta", depends_on=["alpha"]), make("alpha")],
        core_version="0.2.0",
    )
    assert [m.id for m in registry] == ["alpha", "beta", "gamma"]
    assert registry.dependents_of("alpha") == ["beta"]


@pytest.mark.parametrize(
    ("manifests", "message"),
    [
        ([make("alpha"), make("alpha")], "declare deux fois"),
        ([make("beta", depends_on=["alpha"])], "absent"),
        ([make("alpha", depends_on=["beta"]), make("beta", depends_on=["alpha"])], "circulaire"),
        ([make("alpha", requires_core=">=0.5")], "exige le Core >=0.5"),
    ],
)
def test_inconsistent_module_sets_prevent_startup(
    manifests: list[ModuleManifest], message: str
) -> None:
    with pytest.raises(ModuleRegistryError, match=message):
        ModuleRegistry(manifests, core_version="0.2.0")
