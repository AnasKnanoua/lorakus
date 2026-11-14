"""Evaluation du routage par le sens (palier 2, PR 39) sur des specialistes fictifs.

Jeu : tests/evals/intent_routing.json, en deux parties disjointes :
- `tuning` sert a CHOISIR la marge (balayage de 0 a 0,10) ;
- `measure` sert a la MESURER, avec la marge du code de production (DEFAULT_MARGIN), sans
  jamais regler quoi que ce soit dessus. On rapporte aussi la mesure avec la marge choisie
  sur `tuning`, pour savoir s'il faut changer DEFAULT_MARGIN (et seulement sur cette base).

Comme en apprentissage supervise : on ne regle jamais un hyperparametre sur le jeu de test,
sinon la mesure devient optimiste. Mot-cles (palier 1) volontairement absents : on ne mesure
que le palier 2.

Deux regimes : faux modele (sac de mots, mecanique seulement) par defaut ; vrai modele avec
LORAKUS_EMBEDDING_MODEL_DIR (job de la CI). Objectif fixe AVANT la premiere mesure : 90 % de
bonnes decisions sur `measure` avec le vrai modele (bon specialiste, ou aucun). Rapport ecrit
dans LORAKUS_ROUTING_EVAL_REPORT s'il est defini.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from lorakus.ai.embeddings import Embedder, FakeEmbedder
from lorakus.ai.providers.onnx_embedder import OnnxEmbedder
from lorakus.core.agents.contract import SpecialistContext, SpecialistProfile, SpecialistReport
from lorakus.core.agents.routing import DEFAULT_MARGIN, NONE, IntentRouter

pytestmark = pytest.mark.anyio

DATASET = Path(__file__).with_name("intent_routing.json")
MODEL_DIR = os.environ.get("LORAKUS_EMBEDDING_MODEL_DIR", "")
REAL_MODEL = bool(MODEL_DIR) and (Path(MODEL_DIR) / "model.onnx").is_file()
OBJECTIVE = 0.90
MARGINS = [round(step * 0.005, 3) for step in range(21)]  # 0 a 0,10


async def _handler(_ctx: SpecialistContext) -> SpecialistReport:
    return SpecialistReport(status="no_data", summary="Fictif.")


def _profiles(data: dict[str, Any]) -> list[SpecialistProfile]:
    return [
        SpecialistProfile(
            name=name,
            display_name=name,
            intents=list(intents),
            limits="Fictif.",
            handler=_handler,
            examples=intents,
        )
        for name, intents in data["specialists"].items()
    ]


def _embedder() -> Embedder:
    return OnnxEmbedder.load(Path(MODEL_DIR), threads=2) if REAL_MODEL else FakeEmbedder()


def _decide(best: str | None, score: float | None, runner_up: float | None, margin: float) -> str:
    """Rejoue la regle de IntentRouter._meaning a partir des scores bruts."""
    if best is None or best == NONE or score is None or runner_up is None:
        return NONE
    return best if score - runner_up >= margin else NONE


async def _scores(
    router: IntentRouter, profiles: list[SpecialistProfile], items: list[Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        routing = await router.route(item["q"], profiles)
        out.append(
            {
                "q": item["q"],
                "expected": item["expected"],
                "best": routing.best,
                "score": routing.score,
                "runner_up": routing.runner_up,
            }
        )
    return out


def _accuracy(scored: list[dict[str, Any]], margin: float) -> float:
    hits = [_decide(s["best"], s["score"], s["runner_up"], margin) == s["expected"] for s in scored]
    return sum(hits) / len(hits)


def _write_report(report: dict[str, Any]) -> None:
    """Rapport JSON pour le resume du job de la CI (LORAKUS_ROUTING_EVAL_REPORT)."""
    if path := os.environ.get("LORAKUS_ROUTING_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def test_decision_rule_matches_the_router() -> None:
    assert _decide("focus.day_plan", 0.86, 0.82, 0.03) == "focus.day_plan"
    assert _decide("focus.day_plan", 0.84, 0.82, 0.03) == NONE  # ambigu
    assert _decide(NONE, 0.9, 0.8, 0.03) == NONE


async def test_routing_quality() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    profiles = _profiles(data)
    # Marge nulle pour obtenir les scores bruts ; la decision est rejouee pour chaque marge.
    router = IntentRouter(_embedder(), margin=0.0)
    tuning = await _scores(router, profiles, data["tuning"])
    measure = await _scores(router, profiles, data["measure"])

    by_margin = {m: _accuracy(tuning, m) for m in MARGINS}
    tuned = max(MARGINS, key=lambda m: (by_margin[m], -m))  # meilleure, puis la plus petite
    production = _accuracy(measure, DEFAULT_MARGIN)
    report = {
        "model": "reel" if REAL_MODEL else "faux (sac de mots)",
        "default_margin": DEFAULT_MARGIN,
        "tuned_margin": tuned,
        "tuning_accuracy_by_margin": by_margin,
        "measure_accuracy_default_margin": round(production, 3),
        "measure_accuracy_tuned_margin": round(_accuracy(measure, tuned), 3),
        "objective": OBJECTIVE,
        "measure_errors": [
            {**s, "decided": _decide(s["best"], s["score"], s["runner_up"], DEFAULT_MARGIN)}
            for s in measure
            if _decide(s["best"], s["score"], s["runner_up"], DEFAULT_MARGIN) != s["expected"]
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    _write_report(report)

    assert len(measure) == 30 and len(tuning) == 20
    if REAL_MODEL:
        assert production >= OBJECTIVE, f"routage {production:.3f} < objectif {OBJECTIVE}"
