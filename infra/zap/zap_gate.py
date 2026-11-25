#!/usr/bin/env python3
# pyright: strict
"""Barriere du scan ZAP (P6, PR 57) : lit le rapport JSON et decide.

Bloquante : toute alerte de risque Low, Medium ou High, sauf celles que le plan
(infra/zap/baseline.yaml, job alertFilter) a marquees False Positive (confiance 0 dans le
rapport). Les alertes Informational sont listees sans bloquer.

Pourquoi pas le job exitStatus de ZAP : avec ZAP 2.17, il ignore une alerte bloquante des
qu'une autre variante de la meme regle est filtree (verifie : 10055-5 "script-src
unsafe-inline" non bloquee quand 10055-6 "style-src unsafe-inline" est acceptee).

Ecrit sur la sortie standard un tableau Markdown (resume du run GitHub). Code de sortie :
0 rien de bloquant, 1 au moins une alerte bloquante, 2 rapport illisible ou vide.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

RISKS = ("Informational", "Low", "Medium", "High")
CONFIDENCES = ("False Positive", "Low", "Medium", "High", "Confirmed")
BLOCKING_RISK = 1  # Low


class ReportError(Exception):
    """Rapport absent, illisible ou sans site scanne."""


@dataclass(frozen=True)
class Alert:
    ref: str
    name: str
    risk: int
    confidence: int
    count: int

    @property
    def accepted(self) -> bool:
        """Marquee False Positive par une exception du plan."""
        return self.confidence == 0

    @property
    def blocking(self) -> bool:
        return self.risk >= BLOCKING_RISK and not self.accepted

    @property
    def status(self) -> str:
        if self.blocking:
            return "BLOQUANTE"
        if self.accepted:
            return "acceptee (plan)"
        return "information"


def _object(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportError(f"rapport : {what} illisible")
    return cast(dict[str, Any], value)


def _array(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReportError(f"rapport : {what} illisible")
    return cast(list[Any], value)


def load_alerts(report: object) -> list[Alert]:
    sites = _array(_object(report, "objet").get("site"), "liste des sites")
    if not sites:
        raise ReportError("rapport : aucun site scanne")
    alerts: list[Alert] = []
    for site in sites:
        for item in _array(_object(site, "site").get("alerts", []), "liste d'alertes"):
            raw = _object(item, "alerte")
            try:
                alerts.append(
                    Alert(
                        ref=str(raw.get("alertRef") or raw["pluginid"]),
                        name=str(raw["name"]),
                        risk=int(raw["riskcode"]),
                        confidence=int(raw["confidence"]),
                        count=int(raw.get("count", 0)),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ReportError(f"rapport : alerte illisible ({error})") from error
    return alerts


def summary(alerts: Sequence[Alert]) -> str:
    blocking = [a for a in alerts if a.blocking]
    head = (
        f"**ZAP baseline : {len(blocking)} alerte(s) bloquante(s)**"
        if blocking
        else "**ZAP baseline : aucune alerte bloquante**"
    )
    lines = [
        head,
        "",
        "| Statut | Regle | Alerte | Risque | Confiance | Occurrences |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    ordered = sorted(alerts, key=lambda a: (not a.blocking, -a.risk, a.ref))
    for a in ordered:
        risk = RISKS[a.risk] if 0 <= a.risk < len(RISKS) else str(a.risk)
        confidence = (
            CONFIDENCES[a.confidence] if 0 <= a.confidence < len(CONFIDENCES) else str(a.confidence)
        )
        lines.append(f"| {a.status} | {a.ref} | {a.name} | {risk} | {confidence} | {a.count} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage : zap_gate.py RAPPORT.json", file=sys.stderr)
        return 2
    try:
        alerts = load_alerts(json.loads(Path(args[0]).read_text(encoding="utf-8")))
    except (OSError, ValueError, ReportError) as error:
        print(f"ZAP baseline : {error}", file=sys.stderr)
        return 2
    print(summary(alerts), end="")
    return 1 if any(a.blocking for a in alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
