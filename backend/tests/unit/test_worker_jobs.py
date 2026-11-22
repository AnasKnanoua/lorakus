"""Le worker enregistre bien tous les jobs periodiques de la P5 (un import oublie ne se voit
nulle part ailleurs : le job ne tournerait simplement jamais)."""

import lorakus.worker  # noqa: F401 (importer le worker enregistre les jobs du Core)
from lorakus.core.jobs.port import registry
from lorakus.core.modules.registry import ModuleRegistry


def test_every_periodic_job_of_phase_5_is_registered() -> None:
    ModuleRegistry.from_entry_points()  # comme le worker : les manifestes enregistrent les leurs
    names = set(registry.jobs)
    assert {"signals.dispatch", "telegram.poll", "focus.deadline_watch", "focus.briefing"} <= names
