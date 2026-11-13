"""Evaluation de la recherche dans la memoire (PR 37b) : plein texte, vecteurs, hybride.

Jeu : tests/evals/memory_retrieval.json (profil fictif, depot public). Mesures :
- recall@5 : part des bons faits presents dans les 5 premiers resultats, en moyenne ;
- MRR : moyenne de 1 / rang du premier bon fait (1 = toujours en tete).

Deux regimes :
- par defaut, faux modele (sac de mots) : verifie la mecanique et la qualite du plein texte,
  qui est reelle (PostgreSQL). Les chiffres « vecteurs » n'y valent rien ;
- avec LORAKUS_EMBEDDING_MODEL_DIR (job `eval` de la CI, modele verifie par SHA-256) : le vrai
  modele, et les criteres de la PR 37b. Rapport ecrit dans LORAKUS_EVAL_REPORT s'il est defini.

C'est la demarche classique d'evaluation d'un systeme de recherche (RAG) : un jeu etiquete
a la main, des metriques de rang, une comparaison avec des bases simples.

Premiere mesure avec le vrai modele (CI, 2026-11-13) : plein texte recall@5 0,505 et MRR
0,407 ; vecteurs 0,807 et 0,698 ; hybride 0,828 et 0,656. L'objectif de 0,85 fixe AVANT toute
mesure n'est pas atteint : les trois questions manquees le sont aussi par les vecteurs seuls
(vocabulaire du petit modele : « partiel » / « examen », « famille » / « parents »,
« reveilles » / « se leve »). Les seuils ci-dessous sont donc des GARDE-FOUS DE REGRESSION
poses sous la mesure, pas des objectifs ; on ne regle pas la fusion sur ces 32 questions
(sur-apprentissage d'un jeu trop petit). Ameliorer : plus de questions, puis un modele plus
grand si la memoire le permet (ROADMAP, Idees).
"""

import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from lorakus.ai.embeddings import Embedder, FakeEmbedder
from lorakus.ai.providers.onnx_embedder import OnnxEmbedder
from lorakus.core.identity.service import IdentityService
from lorakus.core.memory.search import (
    lexical_ranking,
    reciprocal_rank_fusion,
    vector_ranking,
)
from lorakus.core.memory.service import MemoryService
from lorakus.db.database import Database

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

DATASET = Path(__file__).with_name("memory_retrieval.json")
MODEL_DIR = os.environ.get("LORAKUS_EMBEDDING_MODEL_DIR", "")
REAL_MODEL = bool(MODEL_DIR) and (Path(MODEL_DIR) / "model.onnx").is_file()
K = 5
# Garde-fous de regression avec le vrai modele, poses sous la premiere mesure (voir plus haut).
RECALL_FLOOR = 0.80
MRR_FLOOR = 0.62


def recall_at_k(ranking: Sequence[str], expected: Sequence[str], k: int = K) -> float:
    return len(set(ranking[:k]) & set(expected)) / len(expected)


def reciprocal_rank(ranking: Sequence[str], expected: Sequence[str]) -> float:
    for rank, key in enumerate(ranking, start=1):
        if key in expected:
            return 1.0 / rank
    return 0.0


def test_metrics_on_known_cases() -> None:
    assert recall_at_k(["a", "b", "c"], ["a", "z"]) == 0.5
    assert recall_at_k(["x"] * 5 + ["a"], ["a"]) == 0.0
    assert reciprocal_rank(["x", "a"], ["a"]) == 0.5
    assert reciprocal_rank(["x"], ["a"]) == 0.0


def _embedder() -> Embedder:
    return OnnxEmbedder.load(Path(MODEL_DIR), threads=2) if REAL_MODEL else FakeEmbedder()


async def _evaluate(database: Database, identity: IdentityService) -> dict[str, Any]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    user = await identity.create_owner("eval@example.com", "mot de passe de test assez long")
    embedder = _embedder()
    memory = MemoryService(database, embedder=embedder)
    key_of: dict[uuid.UUID, str] = {}
    for key, (category, content) in data["facts"].items():
        key_of[(await memory.add_fact(user, content, category)).id] = key
    await memory.index_facts(user)

    scores: dict[str, dict[str, float]] = {
        m: {"recall": 0.0, "mrr": 0.0} for m in ("lexical", "vector", "hybrid")
    }
    misses: list[str] = []
    # Classements de chaque methode, pour comparer des variantes de fusion sans relancer.
    per_query: list[dict[str, Any]] = []
    for question, expected in data["queries"]:
        vector = await embedder.embed_query(question)
        async with database.transaction(user) as session:
            lexical = await lexical_ranking(session, question, personal_only=True)
            vectors = await vector_ranking(session, vector, embedder.model_id, personal_only=True)
        hybrid = reciprocal_rank_fusion([lexical, vectors])
        for name, ranking in (("lexical", lexical), ("vector", vectors), ("hybrid", hybrid)):
            keys = [key_of[f] for f in ranking]
            scores[name]["recall"] += recall_at_k(keys, expected)
            scores[name]["mrr"] += reciprocal_rank(keys, expected)
        per_query.append(
            {
                "question": question,
                "expected": expected,
                "lexical": [key_of[f] for f in lexical[:10]],
                "vector": [key_of[f] for f in vectors[:10]],
            }
        )
        top = [key_of[f] for f in hybrid[:K]]
        if not set(top) & set(expected):
            misses.append(f"{question} -> attendu {expected}, obtenu {top}")

    n = len(data["queries"])
    report: dict[str, Any] = {
        "model": embedder.model_id,
        "queries": n,
        **{m: {k: round(v / n, 3) for k, v in s.items()} for m, s in scores.items()},
        "hybrid_misses": misses,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))  # lisible dans le journal (-s)
    _write_report({**report, "per_query": per_query})
    return report


def _write_report(report: dict[str, Any]) -> None:
    """Rapport JSON pour le resume du job de la CI (LORAKUS_EVAL_REPORT)."""
    if path := os.environ.get("LORAKUS_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def test_retrieval_quality(database: Database, identity: IdentityService) -> None:
    report = await _evaluate(database, identity)
    n = report["queries"]
    # Tolerance d'une question : la fusion peut perdre un cas limite face a la meilleure
    # methode seule sans que ce soit un recul.
    tolerance = 1 / n

    # Valable dans les deux regimes : la fusion ne degrade jamais le plein texte.
    assert report["hybrid"]["recall"] >= report["lexical"]["recall"] - tolerance

    if REAL_MODEL:
        best = max(report["lexical"]["recall"], report["vector"]["recall"])
        assert report["hybrid"]["recall"] >= best - tolerance, report
        assert report["hybrid"]["recall"] >= RECALL_FLOOR, report
        assert report["hybrid"]["mrr"] >= MRR_FLOOR, report
    else:
        # Faux modele : seule la mecanique compte ; le plein texte doit deja servir a quelque
        # chose sur les questions qui partagent un mot avec le bon fait.
        assert report["lexical"]["recall"] > 0.2, report
