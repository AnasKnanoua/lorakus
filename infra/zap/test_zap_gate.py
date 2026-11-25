# pyright: strict
"""Tests de la barriere ZAP. Rapports au format reel de ZAP 2.17 (champs utiles seulement).

Lances par ``make zap-check`` (donc par ``make check`` et la CI).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import zap_gate as gate


def alert(ref: str, name: str, risk: int, confidence: int, count: int = 1) -> dict[str, Any]:
    return {
        "pluginid": ref.split("-")[0],
        "alertRef": ref,
        "name": name,
        "riskcode": str(risk),
        "confidence": str(confidence),
        "count": str(count),
    }


def report(*alerts: dict[str, Any]) -> dict[str, Any]:
    return {
        "@version": "2.17.0",
        "site": [{"@name": "https://lorakus.localhost", "alerts": list(alerts)}],
    }


ACCEPTED_STYLE = alert("10055-6", "CSP: style-src unsafe-inline", 2, 0, 0)
INFO = alert("10109", "Modern Web Application", 0, 2, 3)


class GateTest(unittest.TestCase):
    def run_gate(self, content: str) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zap.json"
            path.write_text(content, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = gate.main([str(path)])
        return code, out.getvalue(), err.getvalue()

    def test_clean_report(self) -> None:
        code, out, _ = self.run_gate(json.dumps(report(ACCEPTED_STYLE, INFO)))
        self.assertEqual(code, 0)
        self.assertIn("aucune alerte bloquante", out)
        self.assertIn("| acceptee (plan) | 10055-6 |", out)
        self.assertIn("| information | 10109 |", out)

    def test_sibling_variant_of_an_accepted_rule_blocks(self) -> None:
        # Cas reel qui a fait ecarter exitStatus : 10055-5 levee a cote de 10055-6 acceptee.
        script = alert("10055-5", "CSP: script-src unsafe-inline", 2, 3, 3)
        code, out, _ = self.run_gate(json.dumps(report(script, ACCEPTED_STYLE, INFO)))
        self.assertEqual(code, 1)
        self.assertIn("1 alerte(s) bloquante(s)", out)
        self.assertTrue(out.splitlines()[4].startswith("| BLOQUANTE | 10055-5 |"), out)

    def test_low_blocks_informational_does_not(self) -> None:
        low = alert("10021", "X-Content-Type-Options Header Missing", 1, 2)
        self.assertEqual(self.run_gate(json.dumps(report(low)))[0], 1)
        self.assertEqual(self.run_gate(json.dumps(report(INFO)))[0], 0)

    def test_blocking_alerts_come_first(self) -> None:
        info_first_by_ref = alert("10015", "Re-examine Cache-control Directives", 0, 1)
        low = alert("10021", "X-Content-Type-Options Header Missing", 1, 2)
        _, out, _ = self.run_gate(json.dumps(report(info_first_by_ref, low)))
        rows = out.splitlines()[4:]
        self.assertTrue(rows[0].startswith("| BLOQUANTE | 10021 |"), out)
        self.assertTrue(rows[1].startswith("| information | 10015 |"), out)

    def test_high_with_low_confidence_still_blocks(self) -> None:
        high = alert("40012", "Cross Site Scripting (Reflected)", 3, 1)
        code, out, _ = self.run_gate(json.dumps(report(high)))
        self.assertEqual(code, 1)
        self.assertIn(
            "| BLOQUANTE | 40012 | Cross Site Scripting (Reflected) | High | Low | 1 |", out
        )

    def test_accepted_only_by_confidence_zero(self) -> None:
        accepted_high = alert("40012", "Cross Site Scripting (Reflected)", 3, 0)
        self.assertEqual(self.run_gate(json.dumps(report(accepted_high)))[0], 0)

    def test_ref_falls_back_to_plugin_id(self) -> None:
        raw = alert("10021", "X-Content-Type-Options Header Missing", 1, 2)
        del raw["alertRef"]
        code, out, _ = self.run_gate(json.dumps(report(raw)))
        self.assertEqual(code, 1)
        self.assertIn("| BLOQUANTE | 10021 |", out)

    def test_several_sites(self) -> None:
        low = alert("10021", "X-Content-Type-Options Header Missing", 1, 2)
        content = report(INFO)
        content["site"].append({"@name": "https://autre", "alerts": [low]})
        self.assertEqual(self.run_gate(json.dumps(content))[0], 1)

    def test_unreadable_or_empty_reports(self) -> None:
        for content in ("pas du json", "[]", json.dumps({"site": []}), json.dumps({}),
                        json.dumps({"site": [{"alerts": "x"}]}),
                        json.dumps(report({"name": "sans risque"}))):  # fmt: skip
            code, out, err = self.run_gate(content)
            self.assertEqual(code, 2, content)
            self.assertEqual(out, "")
            self.assertIn("ZAP baseline :", err)

    def test_missing_file_and_usage(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gate.main(["/nonexistent/zap.json"]), 2)
            self.assertEqual(gate.main([]), 2)
        self.assertIn("usage", err.getvalue())


if __name__ == "__main__":
    unittest.main()
