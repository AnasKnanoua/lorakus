"""Embeddings locaux (PR 37) : faux modele, mise en commun et normalisation de l'adaptateur ONNX.

Le vrai modele n'est pas dans le depot (118 Mo) : l'adaptateur est teste ici avec une fausse
session ONNX et un vrai tokenizer construit en memoire. Le vrai modele est verifie dans
l'image par `python -m lorakus.ai.providers.check` (infra/ci/smoke-image.sh), et par le test
marque `model` quand LORAKUS_EMBEDDING_MODEL_DIR pointe vers ses fichiers.
"""

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import WhitespaceSplit

from lorakus.ai.embeddings import EMBEDDING_DIMENSIONS, EmbeddingError, FakeEmbedder, cosine
from lorakus.ai.providers.onnx_embedder import (
    BATCH_SIZE,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    OnnxEmbedder,
)

pytestmark = pytest.mark.anyio

VOCAB = {"<pad>": 0, "<unk>": 1, "query:": 2, "passage:": 3}
for word in [
    "mon",
    "chien",
    "s'appelle",
    "rex",
    "j'étudie",
    "à",
    "metu",
    "ankara",
    "le",
    "chat",
    "dort",
    "test",
]:
    VOCAB.setdefault(word, len(VOCAB))


def _tokenizer() -> Tokenizer:
    tokenizer = Tokenizer(WordLevel(VOCAB, unk_token="<unk>"))
    tokenizer.pre_tokenizer = WhitespaceSplit()  # pyright: ignore[reportAttributeAccessIssue]
    return tokenizer


class _Node:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSession:
    """Session ONNX factice : l'etat cache d'un jeton depend seulement de son identifiant.

    Les jetons de remplissage recoivent une valeur enorme : s'ils entraient dans la moyenne,
    les tests le verraient tout de suite.
    """

    def __init__(self, with_token_types: bool = True, fail: bool = False) -> None:
        names = ["input_ids", "attention_mask"] + (["token_type_ids"] if with_token_types else [])
        self._inputs = [_Node(n) for n in names]
        self.fail = fail
        self.feeds: list[dict[str, Any]] = []

    def get_inputs(self) -> list[_Node]:
        return self._inputs

    def get_outputs(self) -> list[_Node]:
        return [_Node("last_hidden_state")]

    def run(self, outputs: list[str], feeds: dict[str, Any]) -> list[Any]:
        if self.fail:
            raise RuntimeError("panne ONNX simulee")
        self.feeds.append(feeds)
        ids = feeds["input_ids"]
        hidden = np.zeros((*ids.shape, EMBEDDING_DIMENSIONS), dtype=np.float32)
        for b in range(ids.shape[0]):
            for t in range(ids.shape[1]):
                token = int(ids[b, t])
                if token == VOCAB["<pad>"]:
                    hidden[b, t, :] = 1e6
                else:
                    hidden[b, t, token % EMBEDDING_DIMENSIONS] = 1.0
        return [hidden]


def _embedder(session: FakeSession | None = None) -> OnnxEmbedder:
    tokenizer = _tokenizer()
    tokenizer.enable_padding(pad_id=0, pad_token="<pad>")
    return OnnxEmbedder(session or FakeSession(), tokenizer, "test-model")


def _norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(sum(x * x for x in vector))


# ------------------------------------------------------------------ adaptateur
async def test_vectors_have_the_stored_dimension_and_unit_norm() -> None:
    vectors = await _embedder().embed_passages(["mon chien s'appelle rex", "le chat dort"])

    assert [len(v) for v in vectors] == [EMBEDDING_DIMENSIONS] * 2
    assert all(_norm(v) == pytest.approx(1.0, abs=1e-5) for v in vectors)


async def test_padding_never_enters_the_mean() -> None:
    embedder = _embedder()

    alone = (await embedder.embed_passages(["le chat"]))[0]
    padded = (await embedder.embed_passages(["le chat", "mon chien s'appelle rex à ankara"]))[0]

    assert alone == pytest.approx(padded, abs=1e-6)


async def test_query_and_passage_prefixes_are_added() -> None:
    session = FakeSession()
    embedder = _embedder(session)

    await embedder.embed_query("rex")
    await embedder.embed_passages(["rex"])

    assert int(session.feeds[0]["input_ids"][0, 0]) == VOCAB["query:"]
    assert int(session.feeds[1]["input_ids"][0, 0]) == VOCAB["passage:"]
    assert QUERY_PREFIX.strip() == "query:" and PASSAGE_PREFIX.strip() == "passage:"


async def test_token_types_are_sent_only_when_the_model_expects_them() -> None:
    with_types, without_types = FakeSession(True), FakeSession(False)

    await _embedder(with_types).embed_query("rex")
    await _embedder(without_types).embed_query("rex")

    assert "token_type_ids" in with_types.feeds[0]
    assert "token_type_ids" not in without_types.feeds[0]


async def test_large_inputs_are_split_into_batches_in_order() -> None:
    session = FakeSession()
    texts = ["le chat dort" if i % 2 else "mon chien" for i in range(BATCH_SIZE * 2 + 3)]

    vectors = await _embedder(session).embed_passages(texts)

    assert len(session.feeds) == 3
    assert len(vectors) == len(texts)
    assert vectors[0] != vectors[1] and vectors[0] == vectors[2]


async def test_empty_passage_list_runs_nothing() -> None:
    session = FakeSession()

    assert await _embedder(session).embed_passages([]) == []
    assert session.feeds == []


async def test_runtime_errors_become_embedding_errors() -> None:
    with pytest.raises(EmbeddingError):
        await _embedder(FakeSession(fail=True)).embed_query("rex")


def test_missing_model_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingError, match="absents"):
        OnnxEmbedder.load(tmp_path, threads=1)


# ------------------------------------------------------------------ faux modele
async def test_fake_embedder_is_deterministic_normalized_and_lexical() -> None:
    fake = FakeEmbedder()

    dog = await fake.embed_query("Comment s'appelle mon chien ?")
    passages = await fake.embed_passages(["Mon chien s'appelle Rex", "J'étudie à METU"])

    assert dog == await fake.embed_query("comment s'appelle MON chien ?")
    assert _norm(passages[0]) == pytest.approx(1.0)
    assert cosine(dog, passages[0]) > cosine(dog, passages[1])


async def test_fake_embedder_handles_text_without_words_and_failures() -> None:
    fake = FakeEmbedder()

    assert _norm(await fake.embed_query("?!")) == pytest.approx(1.0)
    fake.fail = True
    with pytest.raises(EmbeddingError):
        await fake.embed_passages(["rex"])


# ------------------------------------------------------------------ vrai modele
REAL_MODEL = os.environ.get("LORAKUS_EMBEDDING_MODEL_DIR", "")


@pytest.mark.skipif(
    not (REAL_MODEL and (Path(REAL_MODEL) / "model.onnx").is_file()),
    reason="fichiers du modele absents (verifies dans l'image par le test de fumee)",
)
async def test_real_model_ranks_the_relevant_fact_first() -> None:
    embedder = OnnxEmbedder.load(Path(REAL_MODEL), threads=2)
    question = await embedder.embed_query("Comment s'appelle mon chien ?")
    facts = await embedder.embed_passages(
        ["Mon labrador s'appelle Rex", "Étudie à METU, à Ankara", "Préfère les réponses courtes"]
    )

    scores = [cosine(question, f) for f in facts]

    assert scores.index(max(scores)) == 0


# ------------------------------------------------------------------ telemetrie
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "identity.onnx"
BACKEND = Path(__file__).resolve().parents[2]


def _session_files(home: Path, import_lorakus_first: bool) -> list[Path]:
    """Ouvre une session ONNX dans un processus neuf ; renvoie les fichiers de telemetrie crees."""
    code = (
        ("import lorakus.ai.providers.onnx_embedder\n" if import_lorakus_first else "")
        + "import onnxruntime\n"
        + f"onnxruntime.InferenceSession({str(FIXTURE)!r}, providers=['CPUExecutionProvider'])\n"
    )
    # Environnement minimal : surtout pas l'ORT_DISABLE_TELEMETRY de ce processus de test.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], cwd=BACKEND, env=env, check=True, capture_output=True
    )
    return [p for p in home.rglob("*") if p.is_file()]


def test_onnx_runtime_telemetry_never_starts(tmp_path: Path) -> None:
    """Notre adaptateur coupe la telemetrie avant l'import d'ONNX Runtime (pitfalls.md)."""
    control = tmp_path / "control"
    control.mkdir()
    if not _session_files(control, import_lorakus_first=False):
        pytest.skip("cette version d'ONNX Runtime ne demarre plus de telemetrie : test sans objet")

    guarded = tmp_path / "guarded"
    guarded.mkdir()

    assert _session_files(guarded, import_lorakus_first=True) == []
