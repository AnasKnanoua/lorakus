"""scripts/new_module.py : copie le gabarit, declare le module, sans laisser de trace du gabarit."""

import importlib.util
import shutil
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("new_module", BACKEND / "scripts" / "new_module.py")
assert spec is not None and spec.loader is not None
new_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_module)


@pytest.fixture
def backend(tmp_path: Path) -> Path:
    (tmp_path / "lorakus_modules").mkdir()
    shutil.copy(BACKEND / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(BACKEND / "alembic.ini", tmp_path / "alembic.ini")
    return tmp_path


def test_creates_a_clean_module(backend: Path) -> None:
    target = new_module.create("study_plan", "study", "Study Plan", backend=backend)

    files = {p.relative_to(target).as_posix() for p in target.rglob("*.py")}
    assert "migrations/study_plan_0001_init.py" in files
    for path in target.rglob("*.py"):
        text = path.read_text("utf-8")
        for leftover in ("template", "Template", "tpl_", "_template"):
            assert leftover not in text, f"{path.name} contient encore '{leftover}'"
    manifest = (target / "manifest.py").read_text("utf-8")
    assert 'id="study_plan"' in manifest
    assert 'table_prefix="study_"' in manifest
    assert 'study_plan = "lorakus_modules.study_plan.manifest:manifest"' in (
        backend / "pyproject.toml"
    ).read_text("utf-8")
    assert "%(here)s/lorakus_modules/study_plan/migrations" in (backend / "alembic.ini").read_text(
        "utf-8"
    )


def test_refuses_bad_names_and_overwrites(backend: Path) -> None:
    for module_id, prefix in (
        ("Bad", "bad"),
        ("template", "tp"),
        ("ok_mod", "core"),
        ("ok_mod", "x"),
    ):
        with pytest.raises(SystemExit):
            new_module.create(module_id, prefix, "X", backend=backend)
    new_module.create("ok_mod", "okm", "Ok", backend=backend)
    with pytest.raises(SystemExit, match="existe deja"):
        new_module.create("ok_mod", "okm", "Ok", backend=backend)
