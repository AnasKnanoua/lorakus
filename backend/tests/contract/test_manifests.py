"""Test de contrat commun a tous les modules (MODULE_SYSTEM.md §2), gabarit compris."""

import configparser
from pathlib import Path

import pytest

from lorakus.core.modules.manifest import ModuleManifest
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.db.base import Base
from lorakus_modules._template.manifest import manifest as template_manifest

BACKEND = Path(__file__).resolve().parents[2]
INSTALLED = list(ModuleRegistry.from_entry_points())
ALL = [*INSTALLED, template_manifest]


def _version_locations() -> list[str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(BACKEND / "alembic.ini")
    raw = parser.get("alembic", "version_locations")
    return [part.replace("%(here)s/", "") for part in raw.split(":")]


@pytest.mark.parametrize("manifest", ALL, ids=lambda m: m.id)
def test_declared_tables_match_models_and_carry_user_id(manifest: ModuleManifest) -> None:
    assert manifest.models is not None or not manifest.data.tables
    if manifest.models:
        __import__(manifest.models)
    for table in manifest.data.tables:
        model = Base.metadata.tables.get(f"lorakus.{table}")
        assert model is not None, f"{manifest.id} : table {table} declaree sans modele"
        assert "user_id" in model.columns, f"{manifest.id} : {table} sans user_id"
    declared = set(manifest.data.tables)
    owned = {
        t.name
        for t in Base.metadata.tables.values()
        if t.name.startswith(manifest.data.table_prefix or "#")
    }
    assert owned <= declared, f"{manifest.id} : tables non declarees {sorted(owned - declared)}"


@pytest.mark.parametrize("manifest", INSTALLED, ids=lambda m: m.id)
def test_installed_module_migrations_are_registered(manifest: ModuleManifest) -> None:
    if manifest.migrations:
        assert f"lorakus_modules/{manifest.id}/migrations" in _version_locations()


@pytest.mark.parametrize("manifest", ALL, ids=lambda m: m.id)
def test_module_has_a_description_and_health(manifest: ModuleManifest) -> None:
    assert manifest.description
    assert manifest.health is not None, f"{manifest.id} : health() manquant"


def test_template_is_not_installed() -> None:
    assert all(m.id != "template" for m in INSTALLED)
