# pyright: strict
"""Tests de la sonde externe : vrais serveurs HTTP et HTTPS locaux, vrais certificats (OpenSSL).

Lances par ``make probe-check`` (donc par ``make check`` et la CI). Il faut ``openssl``
dans le PATH.
"""

from __future__ import annotations

import contextlib
import http.server
import io
import json
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

import external_probe as probe

HOST = "app.lorakus.app"
DAY = 86_400


def _openssl(*args: str, cwd: Path) -> None:
    # Arguments ecrits par les tests eux-memes ; openssl cherche dans le PATH comme en CI.
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def _make_ca(directory: Path, name: str) -> None:
    _openssl(
        "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
        "-keyout", f"{name}.key", "-out", f"{name}.pem", "-days", "30", "-subj", f"/CN={name}",
        "-config", "/dev/null", "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-addext", "subjectKeyIdentifier=hash",
        cwd=directory,
    )  # fmt: skip


def _make_leaf(directory: Path, name: str, dns: str, ca: str, days: int) -> None:
    (directory / f"{name}.ext").write_text(
        f"subjectAltName=DNS:{dns}\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid\n"
    )
    _openssl(
        "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
        "-keyout", f"{name}.key", "-out", f"{name}.csr", "-subj", f"/CN={dns}",
        "-config", "/dev/null",
        cwd=directory,
    )  # fmt: skip
    _openssl(
        "x509", "-req", "-in", f"{name}.csr", "-CA", f"{ca}.pem", "-CAkey", f"{ca}.key",
        "-CAcreateserial", "-out", f"{name}.pem", "-days", str(days), "-extfile", f"{name}.ext",
        cwd=directory,
    )  # fmt: skip


class Behaviour:
    """Ce que repondent les faux serveurs ; remis a zero avant chaque test."""

    status: ClassVar[int] = 200
    body: ClassVar[bytes] = b'{"status":"ok"}'
    hsts: ClassVar[bool] = True
    hang: ClassVar[bool] = False
    https_hits: ClassVar[int] = 0
    redirect_status: ClassVar[int] = 308
    redirect_location: ClassVar[str] = f"https://{HOST}/"
    fail_first: ClassVar[int] = 0

    @classmethod
    def reset(cls) -> None:
        cls.status, cls.body, cls.hsts, cls.hang = 200, b'{"status":"ok"}', True, False
        cls.https_hits, cls.fail_first = 0, 0
        cls.redirect_status, cls.redirect_location = 308, f"https://{HOST}/"


class _Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


class HttpsHandler(_Quiet):
    def do_GET(self) -> None:
        Behaviour.https_hits += 1
        if Behaviour.hang:
            time.sleep(2)
            return
        failing = Behaviour.https_hits <= Behaviour.fail_first
        status = 503 if failing else Behaviour.status
        body = b'{"status":"unavailable"}' if failing else Behaviour.body
        if self.path != probe.HEALTH_PATH:
            status, body = 404, b"{}"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if Behaviour.hsts:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.end_headers()
        self.wfile.write(body)


class HttpHandler(_Quiet):
    def do_GET(self) -> None:
        self.send_response(Behaviour.redirect_status)
        if Behaviour.redirect_location:
            self.send_header("Location", Behaviour.redirect_location)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _Server:
    def __init__(
        self, handler: type[http.server.BaseHTTPRequestHandler], tls: ssl.SSLContext | None
    ):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        if tls is not None:
            self.httpd.socket = tls.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ProbeTestCase(unittest.TestCase):
    tmp: ClassVar[tempfile.TemporaryDirectory[str]]
    certs: ClassVar[Path]
    servers: ClassVar[dict[str, _Server]]

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("openssl") is None:
            raise unittest.SkipTest("openssl absent")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.certs = Path(cls.tmp.name)
        _make_ca(cls.certs, "ca")
        _make_ca(cls.certs, "rogue")
        _make_leaf(cls.certs, "good", HOST, "ca", 90)
        _make_leaf(cls.certs, "othername", "other.example", "ca", 90)
        _make_leaf(cls.certs, "untrusted", HOST, "rogue", 90)
        cls.servers = {"http": _Server(HttpHandler, None)}
        for name in ("good", "othername", "untrusted"):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(cls.certs / f"{name}.pem", cls.certs / f"{name}.key")
            cls.servers[name] = _Server(HttpsHandler, context)

    @classmethod
    def tearDownClass(cls) -> None:
        for server in cls.servers.values():
            server.close()
        cls.tmp.cleanup()

    def setUp(self) -> None:
        Behaviour.reset()
        self.sleeps: list[float] = []

    def target(self, cert: str = "good", http_port: int | None = None) -> probe.Target:
        return probe.Target(
            host=HOST,
            address="127.0.0.1",
            https_port=self.servers[cert].port,
            http_port=self.servers["http"].port if http_port is None else http_port,
            cafile=str(self.certs / "ca.pem"),
        )

    def run_probe(self, target: probe.Target | None = None, **kwargs: Any) -> probe.Report:
        kwargs.setdefault("timeout", 1.0)
        return probe.run(target or self.target(), sleep=self.sleeps.append, **kwargs)


class HealthyTest(ProbeTestCase):
    def test_everything_fine(self) -> None:
        report = self.run_probe()
        self.assertTrue(report.ok, report.line)
        self.assertTrue(report.line.startswith(f"OK {HOST} : santé 200, HSTS, redirection HTTP"))
        self.assertIn("j restants sur 90,0 (seuil 15,0)", report.line)
        self.assertEqual(Behaviour.https_hits, 1)
        self.assertEqual(self.sleeps, [])

    def test_transient_failure_is_retried(self) -> None:
        Behaviour.fail_first = 1
        report = self.run_probe(delay=7.0)
        self.assertTrue(report.ok, report.line)
        self.assertIn("(2 essais)", report.line)
        self.assertEqual(self.sleeps, [7.0])


class TlsTest(ProbeTestCase):
    def test_untrusted_authority(self) -> None:
        report = self.run_probe(self.target("untrusted"), attempts=1)
        self.assertFalse(report.ok)
        self.assertIn("TLS : certificat refusé", report.line)

    def test_wrong_name(self) -> None:
        report = self.run_probe(self.target("othername"), attempts=1)
        self.assertFalse(report.ok)
        self.assertIn("TLS : certificat refusé", report.line)
        self.assertIn("Hostname mismatch", report.line)

    def test_system_store_used_without_cafile(self) -> None:
        target = probe.Target(
            host=HOST, address="127.0.0.1", https_port=self.servers["good"].port,
            http_port=self.servers["http"].port,
        )  # fmt: skip
        self.assertIn("TLS : certificat refusé", self.run_probe(target, attempts=1).line)

    def test_near_expiry_fails_through_the_real_certificate(self) -> None:
        end = subprocess.run(
            ["openssl", "x509", "-noout", "-enddate", "-in", "good.pem"],  # noqa: S607
            cwd=self.certs, check=True, capture_output=True, text=True,
        ).stdout  # fmt: skip
        not_after = ssl.cert_time_to_seconds(end.strip().removeprefix("notAfter="))
        report = self.run_probe(attempts=1, clock=lambda: not_after - 10 * DAY)
        self.assertFalse(report.ok)
        self.assertTrue(report.line.startswith(f"ÉCHEC {HOST} (1 essai) : "), report.line)
        self.assertIn(
            "certificat 10,0 j restants sur 90,0 (seuil 15,0) : le renouvellement échoue",
            report.line,
        )


class HealthTest(ProbeTestCase):
    def test_server_error(self) -> None:
        Behaviour.status, Behaviour.body = 503, b'{"status":"unavailable"}'
        report = self.run_probe(attempts=3)
        self.assertFalse(report.ok)
        self.assertEqual(report.line, f"ÉCHEC {HOST} (3 essais) : {probe.HEALTH_PATH} : 503")
        self.assertEqual(Behaviour.https_hits, 3)
        self.assertEqual(self.sleeps, [probe.RETRY_DELAY_SECONDS] * 2)

    def test_client_error_with_ok_body(self) -> None:
        Behaviour.status = 429
        self.assertIn(f"{probe.HEALTH_PATH} : 429", self.run_probe(attempts=1).line)

    def test_html_page_instead_of_api(self) -> None:
        Behaviour.body = b"<!doctype html><title>Lorakus</title>"
        self.assertIn("200 mais pas la réponse de l'API", self.run_probe(attempts=1).line)

    def test_json_not_ok(self) -> None:
        Behaviour.body = json.dumps({"status": "unavailable"}).encode()
        self.assertIn("200 mais pas la réponse de l'API", self.run_probe(attempts=1).line)

    def test_json_list(self) -> None:
        Behaviour.body = b'["ok"]'
        self.assertIn("200 mais pas la réponse de l'API", self.run_probe(attempts=1).line)

    def test_missing_hsts(self) -> None:
        Behaviour.hsts = False
        self.assertIn("en-tête HSTS absent", self.run_probe(attempts=1).line)

    def test_timeout(self) -> None:
        Behaviour.hang = True
        started = time.monotonic()
        report = self.run_probe(attempts=1, timeout=0.3)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("HTTPS injoignable : délai dépassé", report.line)

    def test_https_port_closed(self) -> None:
        target = probe.Target(
            host=HOST, address="127.0.0.1", https_port=_free_port(),
            http_port=self.servers["http"].port, cafile=str(self.certs / "ca.pem"),
        )  # fmt: skip
        self.assertIn("HTTPS injoignable", self.run_probe(target, attempts=1).line)


class RedirectTest(ProbeTestCase):
    def test_http_port_closed(self) -> None:
        report = self.run_probe(self.target(http_port=_free_port()), attempts=1)
        self.assertFalse(report.ok)
        self.assertIn("HTTP (port", report.line)
        self.assertIn("injoignable", report.line)
        self.assertEqual(Behaviour.https_hits, 0)

    def test_no_redirect(self) -> None:
        Behaviour.redirect_status, Behaviour.redirect_location = 200, ""
        self.assertIn(": 200 sans redirection vers HTTPS", self.run_probe(attempts=1).line)

    def test_redirect_elsewhere(self) -> None:
        Behaviour.redirect_location = "https://evil.example/"
        self.assertIn("sans redirection vers HTTPS", self.run_probe(attempts=1).line)

    def test_redirect_to_plain_http(self) -> None:
        Behaviour.redirect_location = f"http://{HOST}/"
        self.assertIn("sans redirection vers HTTPS", self.run_probe(attempts=1).line)

    def test_redirect_to_lookalike_host(self) -> None:
        Behaviour.redirect_location = f"https://{HOST}.evil.example/"
        self.assertIn("sans redirection vers HTTPS", self.run_probe(attempts=1).line)

    def test_other_redirect_codes(self) -> None:
        for code in (301, 302, 307):
            Behaviour.redirect_status = code
            self.assertTrue(self.run_probe(attempts=1).ok, code)
        Behaviour.redirect_status = 303
        self.assertFalse(self.run_probe(attempts=1).ok)


class CertificateRuleTest(unittest.TestCase):
    def test_boundaries(self) -> None:
        start, end = 0.0, 90.0 * DAY
        self.assertIn("15,0 j restants", probe.check_certificate(start, end, end - 15 * DAY))
        with self.assertRaisesRegex(probe.ProbeError, "le renouvellement échoue"):
            probe.check_certificate(start, end, end - 15 * DAY + 1)

    def test_relative_to_lifetime(self) -> None:
        start, end = 0.0, 6.0 * DAY
        probe.check_certificate(start, end, end - 1 * DAY)
        with self.assertRaises(probe.ProbeError):
            probe.check_certificate(start, end, end - 0.9 * DAY)

    def test_expired_and_incoherent(self) -> None:
        with self.assertRaisesRegex(probe.ProbeError, "certificat expiré"):
            probe.check_certificate(0.0, 90.0 * DAY, 90.0 * DAY)
        with self.assertRaisesRegex(probe.ProbeError, "dates incohérentes"):
            probe.check_certificate(10.0, 10.0, 0.0)


class MainTest(unittest.TestCase):
    def test_exit_codes_and_target(self) -> None:
        seen: list[probe.Target] = []

        def runner(ok: bool) -> Any:
            def fake(target: probe.Target) -> probe.Report:
                seen.append(target)
                return probe.Report(ok, "ligne")

            return fake

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(probe.main([HOST], runner=runner(True)), 0)
            self.assertEqual(probe.main([HOST], runner=runner(False)), 1)
        self.assertEqual(out.getvalue(), "ligne\nligne\n")
        self.assertEqual(seen[0], probe.Target(host=HOST))


if __name__ == "__main__":
    unittest.main()
