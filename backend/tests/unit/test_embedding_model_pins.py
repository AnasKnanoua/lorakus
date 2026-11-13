"""Le script de la CI et l'image telechargent exactement les memes fichiers (PR 37b)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
URL_AND_SHA = re.compile(r"(https://huggingface\.co/[\w./-]+)|([0-9a-f]{64})")


def _pins(text: str) -> list[str]:
    return [a or b for a, b in URL_AND_SHA.findall(text)]


def _model_stage(dockerfile: str) -> str:
    """Seulement l'etape `model` : les autres etapes epinglent des images, pas le modele."""
    start = dockerfile.index("AS model")
    return dockerfile[start : dockerfile.index("\nFROM ", start)]


def test_ci_script_and_dockerfile_pin_the_same_model_files() -> None:
    dockerfile = _pins(_model_stage((ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")))
    script = _pins((ROOT / "infra" / "models" / "fetch-embedding-model.sh").read_text("utf-8"))

    assert len(script) == 4
    assert sorted(dockerfile) == sorted(script)
