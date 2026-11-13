"""Modele d'embeddings local : multilingual-e5-small quantifie (int8), execute par ONNX Runtime.

Choix (ADR 0007, amendement du 2026-11-13) :
- e5 est entraine pour la recherche « question -> passage » et couvre le francais ;
- version int8 : 118 Mo, adaptee a un serveur ARM de 5,6 Go partage avec la base ;
- ONNX Runtime + tokenizers plutot que fastembed : fastembed ne propose pas ce modele,
  telecharge les fichiers au premier usage et ajoute des dependances inutiles ici.

Les fichiers (model.onnx, tokenizer.json) sont integres a l'image pendant sa construction,
epingles par revision et par SHA-256 (backend/Dockerfile) : rien n'est telecharge a
l'execution. Le format ONNX decrit un graphe de calcul ; contrairement a un fichier pickle,
le charger n'execute pas de code.

Une seule inference a la fois dans le processus (verrou) : la memoire et le processeur
restent bornes, et la boucle d'evenements n'est jamais bloquee (calcul dans un thread).
"""

import asyncio
import hashlib
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import numpy.typing as npt

# Telemetrie d'ONNX Runtime coupee AVANT son import. La version Linux embarque un collecteur
# Microsoft (1DS) qui met des evenements d'usage en file pour les envoyer ; l'API a un acces
# sortant (fournisseur d'IA). disable_telemetry_events() apres l'import arrive trop tard : un
# evenement est deja en file (mesure le 2026-11-13, docs/runbooks/pitfalls.md). Valeur forcee :
# une variable externe ne peut pas la reactiver. Aussi posee dans l'image (backend/Dockerfile).
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import onnxruntime  # pyright: ignore[reportMissingTypeStubs]
from tokenizers import Tokenizer

from lorakus.ai.embeddings import EMBEDDING_DIMENSIONS, EmbeddingError, Vector
from lorakus.observability.metrics import EMBED_SECONDS

MODEL_FILE: Final = "model.onnx"
TOKENIZER_FILE: Final = "tokenizer.json"
MODEL_FAMILY: Final = "multilingual-e5-small-q8"
QUERY_PREFIX: Final = "query: "
PASSAGE_PREFIX: Final = "passage: "
MAX_TOKENS: Final = 512
BATCH_SIZE: Final = 16

# ONNX Runtime n'est que partiellement type : on le manipule comme Any, ici seulement.
_ort: Any = onnxruntime


def file_sha256(path: Path) -> str:
    """Empreinte SHA-256 d'un fichier, lu par morceaux (le modele fait 118 Mo)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OnnxEmbedder:
    """Adaptateur du port Embedder. Construire avec OnnxEmbedder.load()."""

    def __init__(self, session: Any, tokenizer: Tokenizer, model_id: str) -> None:
        """session : onnxruntime.InferenceSession (non type)."""
        self._session: Any = session
        self._tokenizer = tokenizer
        self._model_id = model_id
        self._inputs: frozenset[str] = frozenset(str(i.name) for i in session.get_inputs())
        self._output: str = str(session.get_outputs()[0].name)
        self._lock = asyncio.Lock()

    @classmethod
    def load(cls, model_dir: Path, *, threads: int) -> "OnnxEmbedder":
        """Charge le modele et verifie qu'il produit des vecteurs de la bonne dimension."""
        model_path = model_dir / MODEL_FILE
        tokenizer_path = model_dir / TOKENIZER_FILE
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise EmbeddingError(f"fichiers du modele absents dans {model_dir}")
        # L'identifiant suit les fichiers : un autre modele, meme de meme nom, change d'id
        # et ses vecteurs seront recalcules.
        model_id = f"{MODEL_FAMILY}:{file_sha256(model_path)[:12]}"

        options: Any = _ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        # Sans reserve memoire : la memoire d'une inference est rendue au systeme ensuite.
        options.enable_cpu_mem_arena = False
        options.log_severity_level = 3  # erreurs seulement
        try:
            session: Any = _ort.InferenceSession(
                str(model_path), options, providers=["CPUExecutionProvider"]
            )
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as error:  # erreurs propres a ONNX Runtime ou au fichier
            raise EmbeddingError(f"modele illisible : {error}") from error
        configurable: Any = tokenizer  # enable_* non types dans tokenizers
        configurable.enable_truncation(max_length=MAX_TOKENS)
        pad_id = tokenizer.token_to_id("<pad>")
        configurable.enable_padding(pad_id=1 if pad_id is None else pad_id, pad_token="<pad>")  # noqa: S106

        embedder = cls(session, tokenizer, model_id)
        probe = embedder.encode([QUERY_PREFIX + "test"])
        if len(probe[0]) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"le modele produit {len(probe[0])} dimensions au lieu de {EMBEDDING_DIMENSIONS}"
            )
        return embedder

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIMENSIONS

    async def embed_query(self, text: str) -> Vector:
        return (await self._run("query", [QUERY_PREFIX + text]))[0]

    async def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        if not texts:
            return []
        return await self._run("passages", [PASSAGE_PREFIX + t for t in texts])

    async def _run(self, kind: str, texts: list[str]) -> list[Vector]:
        async with self._lock:
            started = time.perf_counter()
            vectors = await asyncio.to_thread(self.encode, texts)
            EMBED_SECONDS.labels(kind=kind).observe(time.perf_counter() - started)
            return vectors

    def encode(self, texts: Sequence[str]) -> list[Vector]:
        """Calcul synchrone (thread) : moyenne des etats caches ponderee par le masque, normee."""
        vectors: list[Vector] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            try:
                vectors.extend(self._encode_batch(batch))
            except EmbeddingError:
                raise
            except Exception as error:  # erreurs propres a ONNX Runtime
                raise EmbeddingError(f"inference impossible : {error}") from error
        return vectors

    def _encode_batch(self, batch: list[str]) -> list[Vector]:
        encodings = self._tokenizer.encode_batch(batch)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds: dict[str, npt.NDArray[np.int64]] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        outputs = cast(list[object], self._session.run([self._output], feeds))
        hidden = np.asarray(outputs[0], dtype=np.float32)
        if hidden.ndim != 3:
            raise EmbeddingError(f"sortie inattendue du modele : {hidden.shape}")
        weights = mask[..., np.newaxis].astype(np.float32)
        summed = (hidden * weights).sum(axis=1)
        counts = np.clip(weights.sum(axis=1), 1e-9, None)
        mean = summed / counts
        norms = np.clip(np.linalg.norm(mean, axis=1, keepdims=True), 1e-12, None)
        normalized = mean / norms
        return [tuple(float(x) for x in row) for row in normalized]
