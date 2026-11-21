"""Routage des vraies phrases du Sergent (PR 50) avec son vrai profil : mots-cles, puis sens.

Jeu : tests/evals/sergent_routing.json, deux parties disjointes. `tuning` a servi a ecrire les
mots-cles et les exemples du profil (lorakus_modules/focus/specialist.py) ; `measure` a ete
ecrite AVANT eux et ne sert qu'a mesurer. On ne retouche pas le profil en regardant les
erreurs de `measure` : sinon la mesure devient optimiste.

Objectif fixe avant mesure : 90 % de bonnes decisions sur `measure` avec le routeur complet
et le vrai modele (job de la CI, LORAKUS_EMBEDDING_MODEL_DIR).

Premiere mesure (2026-11-21, sans le vrai modele) : les mots-cles seuls donnent 22/22 sur
`tuning` et 16/22 (0,727) sur `measure`. Le palier 2 (sens) n'intervient que quand aucun
mot-cle ne correspond ; son effet reel ne se mesure qu'avec le vrai modele, en CI. Les
garde-fous ci-dessous sont poses sous la premiere mesure : ils signalent une regression, ils
ne sont pas l'objectif.

Rapport JSON dans LORAKUS_SERGENT_ROUTING_EVAL_REPORT s'il est defini (resume de la CI).
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from lorakus.ai.embeddings import Embedder, FakeEmbedder
from lorakus.ai.providers.onnx_embedder import OnnxEmbedder
from lorakus.core.agents.routing import NONE, IntentRouter
from lorakus_modules.focus.specialist import PROFILE

pytestmark = pytest.mark.anyio

DATASET = Path(__file__).with_name("sergent_routing.json")
MODEL_DIR = os.environ.get("LORAKUS_EMBEDDING_MODEL_DIR", "")
REAL_MODEL = bool(MODEL_DIR) and (Path(MODEL_DIR) / "model.onnx").is_file()
OBJECTIVE = 0.90  # fixe avant mesure
RULES_FLOOR = 16 / 22  # garde-fou : mots-cles seuls sur `measure` (premiere mesure)


def _embedder() -> Embedder:
    return OnnxEmbedder.load(Path(MODEL_DIR), threads=2) if REAL_MODEL else FakeEmbedder()


async def _decisions(router: IntentRouter, items: list[list[str]]) -> list[dict[str, Any]]:
    decided: list[dict[str, Any]] = []
    for question, expected in items:
        routing = await router.route(question, [PROFILE])
        got = (
            f"{routing.targets[0].specialist}.{routing.targets[0].intent}"
            if routing.targets
            else NONE
        )
        decided.append({"q": question, "expected": expected, "got": got, "tier": routing.tier})
    return decided


def _write_report(report: dict[str, Any]) -> None:
    """Rapport JSON pour le resume du job de la CI."""
    if path := os.environ.get("LORAKUS_SERGENT_ROUTING_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _accuracy(decided: list[dict[str, Any]]) -> float:
    return sum(d["got"] == d["expected"] for d in decided) / len(decided)


async def test_sergent_routing() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert len(data["tuning"]) == 22 and len(data["measure"]) == 22
    tuning_questions = {q for q, _ in data["tuning"]}
    assert tuning_questions.isdisjoint(q for q, _ in data["measure"])

    rules = IntentRouter(None)  # sans modele : mots-cles seuls
    full = IntentRouter(_embedder())
    rules_tuning = await _decisions(rules, data["tuning"])
    rules_measure = await _decisions(rules, data["measure"])
    full_measure = await _decisions(full, data["measure"])
    report = {
        "model": "reel" if REAL_MODEL else "faux (sac de mots)",
        "objective": OBJECTIVE,
        "rules_tuning": round(_accuracy(rules_tuning), 3),
        "rules_measure": round(_accuracy(rules_measure), 3),
        "full_measure": round(_accuracy(full_measure), 3),
        "full_measure_errors": [d for d in full_measure if d["got"] != d["expected"]],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    _write_report(report)

    assert _accuracy(rules_tuning) == 1.0  # les mots-cles ont ete ecrits sur ce jeu
    assert _accuracy(rules_measure) >= RULES_FLOOR
    # Le sens n'est consulte que sans mot-cle : il ne doit pas faire pire que les regles.
    if REAL_MODEL:
        assert _accuracy(full_measure) >= RULES_FLOOR


def test_the_sergent_profile_routes_its_own_examples() -> None:
    # Chaque mot-cle est un mot entier, sans accents : sinon la regle ne s'appliquerait pas.
    from lorakus.core.agents.routing import fold

    for words in PROFILE.keywords.values():
        assert all(fold(word) == word for word in words)
