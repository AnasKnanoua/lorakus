"""Frontieres du moteur IA : SDK confines aux adaptateurs, faux fournisseur hors production."""

import ast
from pathlib import Path

import pytest
from pydantic import SecretStr

from lorakus.ai.embeddings import EmbeddingError, FakeEmbedder
from lorakus.ai.providers import build_embedder, build_providers
from lorakus.settings import Settings

BACKEND = Path(__file__).resolve().parents[2]
PROVIDERS_DIR = BACKEND / "lorakus" / "ai" / "providers"
AI_SDKS = ("anthropic", "openai", "google.genai", "google.generativeai", "mistralai", "groq")
# Moteurs d'inference locaux (PR 37) : confines eux aussi aux adaptateurs.
LOCAL_RUNTIMES = ("onnxruntime", "tokenizers", "fastembed", "sentence_transformers", "torch")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_ai_sdks_are_imported_only_by_provider_adapters() -> None:
    offenders: list[str] = []
    for root in (BACKEND / "lorakus", BACKEND / "lorakus_modules"):
        for path in root.rglob("*.py"):
            if PROVIDERS_DIR in path.parents:
                continue
            for module in _imported_modules(path):
                if any(
                    module == sdk or module.startswith(sdk + ".")
                    for sdk in (*AI_SDKS, *LOCAL_RUNTIMES)
                ):
                    offenders.append(f"{path.relative_to(BACKEND)} importe {module}")

    assert offenders == []


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_fake_provider_never_answers_outside_development(environment: str) -> None:
    settings = Settings(environment=environment, anthropic_api_key=SecretStr("sk-test"))  # pyright: ignore[reportArgumentType]

    providers = build_providers(settings)

    assert set(providers) == {"anthropic"}


def test_without_key_production_has_no_provider_at_all() -> None:
    settings = Settings(environment="production")  # pyright: ignore[reportArgumentType]

    assert build_providers(settings) == {}


def test_development_without_key_uses_only_the_fake_provider() -> None:
    settings = Settings(environment="development")  # pyright: ignore[reportArgumentType]

    assert set(build_providers(settings)) == {"fake"}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_missing_embedding_model_stops_startup_outside_development(
    environment: str, tmp_path: Path
) -> None:
    settings = Settings(environment=environment, embedding_model_dir=tmp_path)  # pyright: ignore[reportArgumentType]

    with pytest.raises(EmbeddingError):
        build_embedder(settings)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_missing_embedding_model_uses_the_fake_in_development(
    environment: str, tmp_path: Path
) -> None:
    settings = Settings(environment=environment, embedding_model_dir=tmp_path)  # pyright: ignore[reportArgumentType]

    assert isinstance(build_embedder(settings), FakeEmbedder)


def test_unreadable_embedding_model_is_refused_even_in_development(tmp_path: Path) -> None:
    (tmp_path / "model.onnx").write_bytes(b"pas un modele")
    (tmp_path / "tokenizer.json").write_text("{}")
    settings = Settings(environment="development", embedding_model_dir=tmp_path)  # pyright: ignore[reportArgumentType]

    with pytest.raises(EmbeddingError):
        build_embedder(settings)


def test_no_model_is_ever_downloaded_at_runtime() -> None:
    """Le modele vient de l'image (Dockerfile) : aucun client de telechargement dans le code."""
    offenders: list[str] = []
    for root in (BACKEND / "lorakus", BACKEND / "lorakus_modules"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module in _imported_modules(path):
                if module == "huggingface_hub" or module.startswith("huggingface_hub."):
                    offenders.append(f"{path.relative_to(BACKEND)} importe {module}")
            offenders.extend(
                f"{path.relative_to(BACKEND)} appelle {node.attr}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr in {"from_pretrained", "hf_hub_download", "snapshot_download"}
            )

    assert offenders == []
