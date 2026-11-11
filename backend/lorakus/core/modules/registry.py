"""Registre des modules : decouverte, verification de compatibilite, ordre de demarrage.

Le Core ne connait aucun module par son nom : il les trouve par l'entry point
``lorakus.modules`` declare dans pyproject.toml. Toute incoherence (doublon, dependance
absente ou circulaire, Core incompatible) empeche le demarrage, avec un message explicite.
"""

from collections.abc import Iterable, Iterator
from importlib.metadata import entry_points
from typing import Final

from packaging.specifiers import SpecifierSet
from packaging.version import Version

import lorakus
from lorakus.core.modules.manifest import ModuleManifest

ENTRY_POINT_GROUP: Final = "lorakus.modules"


class ModuleRegistryError(RuntimeError):
    """Ensemble de modules incoherent : l'application ne doit pas demarrer."""


class ModuleRegistry:
    """Modules installes, dans un ordre ou chacun vient apres ses dependances."""

    def __init__(
        self, manifests: Iterable[ModuleManifest], core_version: str | None = None
    ) -> None:
        core = Version(core_version or lorakus.__version__)
        by_id: dict[str, ModuleManifest] = {}
        for manifest in manifests:
            if manifest.id in by_id:
                raise ModuleRegistryError(f"module '{manifest.id}' declare deux fois")
            if core not in SpecifierSet(manifest.requires_core, prereleases=True):
                raise ModuleRegistryError(
                    f"module '{manifest.id}' {manifest.version} exige le Core "
                    f"{manifest.requires_core}, version installee : {core}"
                )
            by_id[manifest.id] = manifest
        for manifest in by_id.values():
            missing = [dep for dep in manifest.depends_on if dep not in by_id]
            if missing:
                raise ModuleRegistryError(
                    f"module '{manifest.id}' depend de module(s) absent(s) : {', '.join(missing)}"
                )
        _check_tools_and_specialists(by_id)
        self._ordered = _topological_order(by_id)
        self._by_id = by_id

    @classmethod
    def from_entry_points(cls) -> "ModuleRegistry":
        """Modules declares par l'entry point lorakus.modules."""
        manifests: list[ModuleManifest] = []
        for point in entry_points(group=ENTRY_POINT_GROUP):
            loaded = point.load()
            if not isinstance(loaded, ModuleManifest):
                raise ModuleRegistryError(
                    f"entry point '{point.name}' ({point.value}) ne designe pas un ModuleManifest"
                )
            if loaded.id != point.name:
                raise ModuleRegistryError(
                    f"entry point '{point.name}' : le manifeste porte l'id '{loaded.id}'"
                )
            manifests.append(loaded)
        return cls(manifests)

    def __iter__(self) -> Iterator[ModuleManifest]:
        return iter(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    def get(self, module_id: str) -> ModuleManifest | None:
        return self._by_id.get(module_id)

    def dependents_of(self, module_id: str) -> list[str]:
        """Modules qui dependent directement de module_id."""
        return [m.id for m in self._ordered if module_id in m.depends_on]


def _topological_order(by_id: dict[str, ModuleManifest]) -> list[ModuleManifest]:
    ordered: list[ModuleManifest] = []
    state: dict[str, str] = {}

    def visit(module_id: str, path: list[str]) -> None:
        if state.get(module_id) == "done":
            return
        if state.get(module_id) == "visiting":
            cycle = " -> ".join([*path[path.index(module_id) :], module_id])
            raise ModuleRegistryError(f"dependance circulaire : {cycle}")
        state[module_id] = "visiting"
        for dep in by_id[module_id].depends_on:
            visit(dep, [*path, module_id])
        state[module_id] = "done"
        ordered.append(by_id[module_id])

    for module_id in sorted(by_id):
        visit(module_id, [])
    return ordered


def _check_tools_and_specialists(by_id: dict[str, ModuleManifest]) -> None:
    # Imports locaux : outils et specialistes s'appuient sur le manifeste (pas de cycle).
    from lorakus.core.agents.contract import SpecialistProfile
    from lorakus.core.tools.spec import ToolSpec

    intents: dict[str, str] = {}
    for manifest in by_id.values():
        for tool in manifest.tools:
            if not isinstance(tool, ToolSpec):
                raise ModuleRegistryError(
                    f"module '{manifest.id}' : outil qui n'est pas un ToolSpec"
                )
        spec = manifest.specialist
        if spec is None:
            continue
        if not isinstance(spec, SpecialistProfile):
            raise ModuleRegistryError(f"module '{manifest.id}' : specialiste invalide")
        for intent in spec.intents:
            if intent in intents:
                raise ModuleRegistryError(
                    f"intention '{intent}' revendiquee par '{intents[intent]}' et '{manifest.id}'"
                )
            intents[intent] = manifest.id
