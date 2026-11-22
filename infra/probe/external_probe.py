#!/usr/bin/env python3
# pyright: strict
"""Sonde externe de l'adresse publique de Lorakus, lancee depuis Internet (ADR 0037, amendement P6).

Verifie ce que la supervision interne ne peut pas voir : le chemin complet depuis Internet
(DNS, pare-feu, liste de securite Oracle, Caddy, API, base) et le certificat.

1. HTTP (port 80) : redirection vers HTTPS. Le port 80 sert aussi au renouvellement Let's Encrypt.
2. HTTPS : certificat accepte par le magasin du systeme et valable pour le nom ; reponse 200
   ``{"status": "ok"}`` de ``/api/health/ready`` (une page HTML voudrait dire que /api n'atteint
   plus l'API) ; en-tête HSTS (la reponse vient bien de notre Caddy).
3. Certificat : il doit rester au moins un sixieme de sa duree de vie. Caddy renouvelle quand il
   en reste un tiers ; passe un sixieme, le renouvellement échoue depuis longtemps. Seuil relatif :
   reste juste si l'autorite raccourcit ses certificats.

Bibliotheque standard seulement (aucune dependance a installer sur le runner). Code de sortie 0
si tout va bien, 1 sinon ; le compte rendu tient en une ligne, sans aucun secret.
"""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import ssl
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

HEALTH_PATH = "/api/health/ready"
TIMEOUT_SECONDS = 10.0
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 20.0
MIN_REMAINING_FRACTION = 1 / 6
MAX_BODY_BYTES = 64 * 1024
REDIRECT_STATUSES = frozenset({301, 302, 307, 308})
DAY_SECONDS = 86_400


class ProbeError(Exception):
    """Echec constate par la sonde ; le message est montre tel quel (aucun secret)."""


@dataclass(frozen=True)
class Target:
    """Ce qui est sonde. ``address``, ``ports`` et ``cafile`` ne servent qu'aux tests."""

    host: str
    address: str | None = None
    https_port: int = 443
    http_port: int = 80
    cafile: str | None = None


@dataclass(frozen=True)
class Report:
    ok: bool
    line: str


class _HTTPSConnection(http.client.HTTPSConnection):
    """Connexion TLS a ``address`` en verifiant le certificat pour ``host``."""

    def __init__(
        self, host: str, port: int, *, address: str | None, context: ssl.SSLContext, timeout: float
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._probe_address = address
        self._probe_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._probe_address or self.host, self.port), self.timeout)
        try:
            self.sock = self._probe_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, address: str | None, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._probe_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._probe_address or self.host, self.port), self.timeout
        )


def check_certificate(not_before: float, not_after: float, now: float) -> str:
    """Renvoie le resume du certificat, ou leve ProbeError s'il faut s'en inquieter."""
    lifetime = not_after - not_before
    if lifetime <= 0:
        raise ProbeError("certificat : dates incohérentes")
    remaining = not_after - now
    threshold = lifetime * MIN_REMAINING_FRACTION
    summary = (
        f"certificat {_days(remaining)} j restants sur {_days(lifetime)} (seuil {_days(threshold)})"
    )
    if remaining <= 0:
        raise ProbeError("certificat expiré")
    if remaining < threshold:
        raise ProbeError(f"{summary} : le renouvellement échoue")
    return summary


def _days(seconds: float) -> str:
    return f"{seconds / DAY_SECONDS:.1f}".replace(".", ",")


def _check_redirect(target: Target, timeout: float) -> None:
    conn = _HTTPConnection(target.host, target.http_port, address=target.address, timeout=timeout)
    try:
        conn.request("GET", "/")
        response = conn.getresponse()
        location = response.getheader("Location", "")
        response.read(MAX_BODY_BYTES)
    except (OSError, http.client.HTTPException) as error:
        raise ProbeError(
            f"HTTP (port {target.http_port}) injoignable : {_reason(error)}"
        ) from error
    finally:
        conn.close()
    if response.status not in REDIRECT_STATUSES or not location.startswith(
        f"https://{target.host}/"
    ):
        raise ProbeError(
            f"HTTP (port {target.http_port}) : {response.status} sans redirection vers HTTPS"
        )


def _check_https(target: Target, timeout: float) -> tuple[float, float]:
    context = ssl.create_default_context(cafile=target.cafile)
    conn = _HTTPSConnection(
        target.host, target.https_port, address=target.address, context=context, timeout=timeout
    )
    try:
        # Certificat lu juste apres la poignee de main : la reponse peut fermer la connexion.
        conn.connect()
        sock = conn.sock
        certificate = sock.getpeercert() if isinstance(sock, ssl.SSLSocket) else None
        conn.request("GET", HEALTH_PATH, headers={"Accept": "application/json"})
        response = conn.getresponse()
        body = response.read(MAX_BODY_BYTES)
        hsts = response.getheader("Strict-Transport-Security")
    except ssl.SSLCertVerificationError as error:
        raise ProbeError(f"TLS : certificat refusé ({error.verify_message})") from error
    except (OSError, http.client.HTTPException) as error:
        raise ProbeError(f"HTTPS injoignable : {_reason(error)}") from error
    finally:
        conn.close()

    if response.status != 200:
        raise ProbeError(f"{HEALTH_PATH} : {response.status}")
    try:
        status = json.loads(body).get("status")
    except (ValueError, AttributeError):
        status = None
    if status != "ok":
        raise ProbeError(f"{HEALTH_PATH} : 200 mais pas la réponse de l'API")
    if not hsts:
        raise ProbeError("en-tête HSTS absent : la réponse ne vient pas de notre Caddy")
    if not certificate:
        raise ProbeError("TLS : certificat illisible")
    return (
        ssl.cert_time_to_seconds(str(certificate["notBefore"])),
        ssl.cert_time_to_seconds(str(certificate["notAfter"])),
    )


def _reason(error: BaseException) -> str:
    if isinstance(error, TimeoutError | socket.timeout):
        return "délai dépassé"
    return str(error) or type(error).__name__


def probe_once(target: Target, *, now: float, timeout: float) -> str:
    _check_redirect(target, timeout)
    not_before, not_after = _check_https(target, timeout)
    certificate = check_certificate(not_before, not_after, now)
    return f"santé 200, HSTS, redirection HTTP, {certificate}"


def run(
    target: Target,
    *,
    attempts: int = ATTEMPTS,
    delay: float = RETRY_DELAY_SECONDS,
    timeout: float = TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> Report:
    """Sonde jusqu'a ``attempts`` fois : un incident reseau d'un instant ne doit pas reveiller."""
    error = ProbeError("aucun essai")
    for attempt in range(1, attempts + 1):
        try:
            summary = probe_once(target, now=clock(), timeout=timeout)
        except ProbeError as caught:
            error = caught
            if attempt < attempts:
                sleep(delay)
            continue
        tries = f" ({attempt} essais)" if attempt > 1 else ""
        return Report(True, f"OK {target.host}{tries} : {summary}")
    tries = f"{attempts} essais" if attempts > 1 else "1 essai"
    return Report(False, f"ÉCHEC {target.host} ({tries}) : {error}")


def main(argv: Sequence[str] | None = None, *, runner: Callable[[Target], Report] = run) -> int:
    parser = argparse.ArgumentParser(
        description="Sonde l'adresse publique de Lorakus depuis Internet."
    )
    parser.add_argument("host", help="nom public, par exemple app.lorakus.app")
    args = parser.parse_args(argv)
    report = runner(Target(host=args.host))
    print(report.line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
