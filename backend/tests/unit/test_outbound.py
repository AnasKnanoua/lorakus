"""Client HTTP sortant (PR 45) : chaque contournement SSRF connu est refuse.

Deux niveaux :
- la politique seule (URL et adresses), sans reseau ;
- le client complet contre un vrai serveur HTTPS local (autorite de certification de test).
  Le resolveur est injecte : on choisit ce que « repond le DNS », y compris un DNS qui change
  d'avis entre deux questions. Seule l'adresse 127.0.0.1 du serveur de test est admise en
  plus des adresses publiques, et seulement dans ces tests.
"""

import gzip
import ipaddress
import ssl
import threading
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from lorakus.core.outbound import (
    FetchLimits,
    InvalidUrlError,
    OutboundError,
    OutboundHttp,
    display_hint,
    is_public_address,
    parse_public_url,
)
from lorakus.core.outbound.policy import IPAddress

pytestmark = pytest.mark.anyio


# --------------------------------------------------------------- l'URL seule
@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://agenda.example.com/a.ics", "https"),
        ("ftp://agenda.example.com/a.ics", "https"),
        ("file:///etc/passwd", "https"),
        ("https://user:secret@agenda.example.com/a.ics", "identifiants"),
        ("https://agenda.example.com@127.0.0.1/a.ics", "identifiants"),
        ("https://127.0.0.1/a.ics", "adresse IP"),
        ("https://[::1]/a.ics", "adresse IP"),
        ("https://[::ffff:127.0.0.1]/a.ics", "adresse IP"),
        ("https://2130706433/a.ics", "adresse IP"),  # 127.0.0.1 en decimal
        ("https://0x7f000001/a.ics", "adresse IP"),  # en hexadecimal
        ("https://0177.0.0.1/a.ics", "adresse IP"),  # en octal
        ("https://127.1/a.ics", "adresse IP"),  # forme courte
        ("https://0x7f.1/a.ics", "adresse IP"),
        ("https://169.254.169.254/latest/meta-data/", "adresse IP"),
        ("https://localhost/a.ics", "reserve"),
        ("https://api.localhost/a.ics", "reserve"),
        ("https://metadata.google.internal/computeMetadata/v1/", "reserve"),
        ("https://imprimante.local/a.ics", "reserve"),
        ("https://box.home.arpa/a.ics", "reserve"),
        ("https://agenda/a.ics", "invalide"),  # nom sans domaine (reseau local)
        ("https://-agenda.example.com/a.ics", "invalide"),
        ("https://agenda.example.com\\@evil.example.com/", "interdits"),
        ("https://agenda.example.com/a .ics", "interdits"),
        ("https://agenda.example.com/a\r\nX: y", "interdits"),
        ("https://agenda.example.com:0/a.ics", "port"),
        ("https://agenda.example.com:99999/a.ics", "invalide"),
        ("https:///a.ics", "domaine"),
        ("https://agenda.example.com/" + "a" * 2100, "trop longue"),
    ],
)
def test_bad_urls_are_refused_before_any_network(url: str, why: str) -> None:
    with pytest.raises(InvalidUrlError, match=why):
        parse_public_url(url)


def test_good_urls_are_normalised() -> None:
    google = parse_public_url(
        "HTTPS://Calendar.Google.com/calendar/ical/a%40gmail.com/private-abc/basic.ics"
    )
    assert google.host == "calendar.google.com" and google.port == 443
    assert google.target == "/calendar/ical/a%40gmail.com/private-abc/basic.ics"
    assert parse_public_url("https://bücher.example/x.ics?k=1").host == "xn--bcher-kva.example"
    other = parse_public_url("https://cal.example.org:8443/x?token=abc#frag")
    assert (other.port, other.target) == (8443, "/x?token=abc")


def test_the_hint_never_shows_any_part_of_the_path() -> None:
    url = parse_public_url("https://cal.example.org/ical/7c1f0a9b3e5d4c2a8f6e1d0b9a8c7e6f")
    assert display_hint(url) == "cal.example.org/…"


# ---------------------------------------------------------- les adresses seules
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # metadonnees (Oracle, AWS, GCP, Azure)
        "100.100.100.200",  # metadonnees d'Alibaba (plage partagee 100.64/10)
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 (adresse testee, aucune ecoute)
        "224.0.0.1",  # multidiffusion : « globale » pour Python
        "233.252.0.1",
        "255.255.255.255",
        "192.88.99.1",  # relais 6to4 : « global » pour Python
        "198.18.0.1",
        "::1",
        "::",
        "fe80::1",
        "fd00:ec2::254",  # metadonnees d'AWS en IPv6
        "ff02::1",
        "::ffff:127.0.0.1",  # IPv4 mappee
        "::ffff:169.254.169.254",
        "::127.0.0.1",  # IPv4 compatible : « globale » pour Python
        "2002:7f00:1::",  # 6to4 de 127.0.0.1
        "2002:a9fe:a9fe::",  # 6to4 de 169.254.169.254
        "64:ff9b::a00:1",  # NAT64 de 10.0.0.1 : « globale » pour Python
        "64:ff9b::a9fe:a9fe",  # NAT64 de 169.254.169.254
        "64:ff9b:1::1",
        "2001::1",  # Teredo
        "2001:db8::1",
    ],
)
def test_private_and_disguised_addresses_are_refused(address: str) -> None:
    assert not is_public_address(ipaddress.ip_address(address))


@pytest.mark.parametrize(
    "address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"]
)
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(ipaddress.ip_address(address))


# ------------------------------------------------------ serveur HTTPS de test
LOOPBACK = ipaddress.IPv4Address("127.0.0.1")
NAMES = ("agenda.example.com", "relais.example.com")


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _cert(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: x509.Certificate | None,
    issuer_key: ec.EllipticCurvePrivateKey,
    names: Sequence[str] = (),
) -> x509.Certificate:
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(
            issuer.subject
            if issuer
            else x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
        )
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True)
        # Extensions exigees par la verification stricte de Python 3.13 (VERIFY_X509_STRICT).
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    )
    if issuer is None:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    if names:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("tls")
    ca_key = _key()
    ca = _cert("Lorakus test CA", ca_key, None, ca_key)
    leaf_key = _key()
    leaf = _cert("agenda", leaf_key, ca, ca_key, NAMES)
    pem = serialization.Encoding.PEM
    files = {"ca": folder / "ca.pem", "cert": folder / "cert.pem", "key": folder / "key.pem"}
    files["ca"].write_bytes(ca.public_bytes(pem))
    files["cert"].write_bytes(leaf.public_bytes(pem) + ca.public_bytes(pem))
    files["key"].write_bytes(
        leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return files


class Handler(BaseHTTPRequestHandler):
    """Reponses scriptees par chemin ; chaque requete est notee (hote demande)."""

    seen: ClassVar[list[tuple[str, str]]] = []
    posted: ClassVar[list[tuple[str, dict[str, str], bytes]]] = []
    ICS: ClassVar[bytes] = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if "Transfer-Encoding" not in (headers or {}):
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        Handler.seen.append((self.headers.get("Host", ""), self.path))
        path = self.path.split("?", 1)[0]
        port = cast(tuple[str, int], self.server.server_address)[1]
        if path == "/ok.ics":
            self._send(200, Handler.ICS, {"Content-Type": "text/calendar; charset=utf-8"})
        elif path == "/hop":
            self._send(302, headers={"Location": "/ok.ics"})
        elif path == "/to-relais":
            self._send(302, headers={"Location": f"https://relais.example.com:{port}/ok.ics"})
        elif path == "/to-private":
            self._send(302, headers={"Location": f"https://prive.example.com:{port}/ok.ics"})
        elif path == "/to-http":
            self._send(302, headers={"Location": f"http://agenda.example.com:{port}/ok.ics"})
        elif path == "/to-ip":
            self._send(302, headers={"Location": "https://169.254.169.254/latest/meta-data/"})
        elif path == "/loop":
            self._send(302, headers={"Location": "/loop"})
        elif path == "/declared-big":
            self.send_response(200)
            self.send_header("Content-Length", str(50 * 1024 * 1024))
            self.end_headers()
            self.wfile.write(b"x" * 1024)
        elif path == "/streamed-big":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"y" * 65536
            try:
                for _ in range(200):
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                return  # le client a coupe : attendu
        elif path == "/bomb":
            bomb = gzip.compress(b"\0" * (64 * 1024 * 1024))  # 64 Mio -> quelques dizaines de Ko
            self._send(200, bomb, {"Content-Encoding": "gzip"})
        elif path == "/gzip":
            self._send(200, gzip.compress(Handler.ICS), {"Content-Encoding": "gzip"})
        elif path == "/brotli":
            self._send(200, b"???", {"Content-Encoding": "br"})
        elif path == "/slow":
            time.sleep(3)
            self._send(200, b"trop tard")
        elif path == "/forbidden":
            self._send(403, b"non")
        else:
            self._send(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        Handler.posted.append((self.path, dict(self.headers.items()), body))
        if self.path == "/push/ok":
            self._send(201)
        elif self.path == "/push/gone":
            self._send(410, b"expired")
        elif self.path == "/push/busy":
            self._send(429, headers={"Retry-After": "60"})
        elif self.path == "/push/hop":
            self._send(307, headers={"Location": "https://prive.example.com/push/ok"})
        elif self.path == "/push/slow":
            time.sleep(3)
            self._send(201)
        else:
            self._send(404)


@pytest.fixture(scope="module")
def server(tls_files: dict[str, Path]) -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2  # jamais TLS 1.0 ni 1.1 (CodeQL)
    context.load_cert_chain(tls_files["cert"], tls_files["key"])
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


class FakeDns:
    """Ce que « repond le DNS » ; chaque question est notee."""

    def __init__(self, answers: dict[str, list[list[str]]]) -> None:
        self.answers = answers
        self.questions: list[str] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.questions.append(host)
        series = self.answers.get(host)
        if not series:
            raise OSError("introuvable")
        # Une serie de reponses : la premiere, puis la suivante a la question suivante...
        return series.pop(0) if len(series) > 1 else series[0]


def only_loopback_or_public(address: IPAddress) -> bool:
    return address == LOOPBACK or is_public_address(address)


def client(tls_files: dict[str, Path], dns: FakeDns) -> OutboundHttp:
    context = ssl.create_default_context(cafile=str(tls_files["ca"]))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return OutboundHttp(resolver=dns, ssl_context=context, address_policy=only_loopback_or_public)


def standard_dns() -> FakeDns:
    return FakeDns(
        {
            "agenda.example.com": [["127.0.0.1"]],
            "relais.example.com": [["127.0.0.1"]],
            "prive.example.com": [["10.0.0.7"]],
        }
    )


@pytest.fixture(autouse=True)
def clear_seen() -> None:
    Handler.seen.clear()
    Handler.posted.clear()


# ------------------------------------------------------------ client complet
async def test_fetches_over_https_with_the_right_host(
    server: int, tls_files: dict[str, Path]
) -> None:
    result = await client(tls_files, standard_dns()).get(
        f"https://agenda.example.com:{server}/ok.ics?jeton=secret"
    )
    assert result.body == Handler.ICS and result.status == 200
    assert result.content_type == "text/calendar; charset=utf-8"
    assert result.host == "agenda.example.com"
    assert Handler.seen == [(f"agenda.example.com:{server}", "/ok.ics?jeton=secret")]


async def test_a_name_resolving_to_a_private_address_is_never_contacted(
    server: int, tls_files: dict[str, Path]
) -> None:
    dns = FakeDns({"agenda.example.com": [["10.0.0.7"]]})
    with pytest.raises(OutboundError) as error:
        await client(tls_files, dns).get(f"https://agenda.example.com:{server}/ok.ics")
    assert error.value.reason == "forbidden_address"
    assert Handler.seen == []


async def test_one_private_address_among_public_ones_refuses_the_name(
    server: int, tls_files: dict[str, Path]
) -> None:
    dns = FakeDns({"agenda.example.com": [["8.8.8.8", "169.254.169.254"]]})
    with pytest.raises(OutboundError) as error:
        await client(tls_files, dns).get(f"https://agenda.example.com:{server}/ok.ics")
    assert error.value.reason == "forbidden_address"


async def test_the_production_policy_refuses_the_loopback_server(
    server: int, tls_files: dict[str, Path]
) -> None:
    """Sans la derogation des tests, le serveur local (127.0.0.1) est injoignable."""
    context = ssl.create_default_context(cafile=str(tls_files["ca"]))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    strict = OutboundHttp(resolver=standard_dns(), ssl_context=context)
    with pytest.raises(OutboundError) as error:
        await strict.get(f"https://agenda.example.com:{server}/ok.ics")
    assert error.value.reason == "forbidden_address"
    assert Handler.seen == []


async def test_the_name_is_resolved_once_per_hop_dns_rebinding(
    server: int, tls_files: dict[str, Path]
) -> None:
    """Le DNS repond d'abord une adresse admise, puis une adresse privee : la connexion vise
    l'adresse verifiee, sans seconde question."""
    dns = FakeDns({"agenda.example.com": [["127.0.0.1"], ["169.254.169.254"]]})
    result = await client(tls_files, dns).get(f"https://agenda.example.com:{server}/ok.ics")
    assert result.status == 200
    assert dns.questions == ["agenda.example.com"]


async def test_redirects_are_followed_and_revalidated(
    server: int, tls_files: dict[str, Path]
) -> None:
    dns = standard_dns()
    http = client(tls_files, dns)
    assert (await http.get(f"https://agenda.example.com:{server}/hop")).redirects == 1
    other = await http.get(f"https://agenda.example.com:{server}/to-relais")
    assert other.host == "relais.example.com" and other.body == Handler.ICS
    assert dns.questions.count("relais.example.com") == 1


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/to-private", "forbidden_address"),  # redirection vers un nom prive
        ("/to-http", "invalid_url"),  # jamais de retour en HTTP
        ("/to-ip", "invalid_url"),  # metadonnees par adresse IP
        ("/loop", "too_many_redirects"),
    ],
)
async def test_dangerous_redirects_are_refused(
    server: int, tls_files: dict[str, Path], path: str, reason: str
) -> None:
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).get(f"https://agenda.example.com:{server}{path}")
    assert error.value.reason == reason
    assert not any(host.startswith("prive.") for host, _ in Handler.seen)
    if path == "/loop":  # 1 requete + 3 redirections suivies, pas une de plus
        assert len(Handler.seen) == FetchLimits().max_redirects + 1


@pytest.mark.parametrize("path", ["/declared-big", "/streamed-big", "/bomb"])
async def test_size_is_bounded_even_compressed(
    server: int, tls_files: dict[str, Path], path: str
) -> None:
    started = time.monotonic()
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).get(
            f"https://agenda.example.com:{server}{path}", limits=FetchLimits(max_bytes=1024 * 1024)
        )
    assert error.value.reason == "too_large"
    assert time.monotonic() - started < 5


async def test_gzip_is_decoded(server: int, tls_files: dict[str, Path]) -> None:
    result = await client(tls_files, standard_dns()).get(
        f"https://agenda.example.com:{server}/gzip"
    )
    assert result.body == Handler.ICS


async def test_unknown_encoding_is_refused(server: int, tls_files: dict[str, Path]) -> None:
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).get(f"https://agenda.example.com:{server}/brotli")
    assert error.value.reason == "encoding"


async def test_total_time_is_bounded(server: int, tls_files: dict[str, Path]) -> None:
    started = time.monotonic()
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).get(
            f"https://agenda.example.com:{server}/slow",
            limits=FetchLimits(read_timeout_s=10, total_timeout_s=1),
        )
    assert error.value.reason == "timeout"
    assert time.monotonic() - started < 2.5


async def test_http_errors_carry_their_status(server: int, tls_files: dict[str, Path]) -> None:
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).get(
            f"https://agenda.example.com:{server}/forbidden"
        )
    assert (error.value.reason, error.value.status) == ("http_status", 403)
    assert "403" in error.value.message


async def test_a_certificate_for_another_name_is_refused(
    server: int, tls_files: dict[str, Path]
) -> None:
    dns = FakeDns({"autre.example.net": [["127.0.0.1"]]})
    with pytest.raises(OutboundError) as error:
        await client(tls_files, dns).get(f"https://autre.example.net:{server}/ok.ics")
    assert error.value.reason == "tls"


async def test_an_untrusted_certificate_is_refused(server: int) -> None:
    """Sans l'autorite de test : le certificat du serveur n'est pas reconnu."""
    http = OutboundHttp(resolver=standard_dns(), address_policy=only_loopback_or_public)
    with pytest.raises(OutboundError) as error:
        await http.get(f"https://agenda.example.com:{server}/ok.ics")
    assert error.value.reason == "tls"


async def test_unknown_names_and_closed_ports(
    server: int, tls_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Les variables de proxy ne sont jamais lues : la requete part quand meme en direct.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    http = client(tls_files, standard_dns())
    assert (await http.get(f"https://agenda.example.com:{server}/ok.ics")).status == 200
    with pytest.raises(OutboundError) as error:
        await http.get("https://inconnu.example.com/ok.ics")
    assert error.value.reason == "dns"
    with pytest.raises(OutboundError) as error:
        await http.get("https://agenda.example.com:9/ok.ics")
    assert error.value.reason == "connect"


# ------------------------------------------------------------------ POST (Web Push)
async def test_post_sends_the_body_and_headers_once(
    server: int, tls_files: dict[str, Path]
) -> None:
    result = await client(tls_files, standard_dns()).post(
        f"https://agenda.example.com:{server}/push/ok",
        b"\x00chiffre\xff",
        [("Content-Encoding", "aes128gcm"), ("TTL", "60")],
    )
    assert (result.status, result.host) == (201, "agenda.example.com")
    [(path, headers, body)] = Handler.posted
    assert path == "/push/ok" and body == b"\x00chiffre\xff"
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "60"
    assert headers["Content-Length"] == "9"


@pytest.mark.parametrize(("path", "status"), [("gone", 410), ("busy", 429), ("absent", 404)])
async def test_post_returns_any_status_as_is(
    server: int, tls_files: dict[str, Path], path: str, status: int
) -> None:
    result = await client(tls_files, standard_dns()).post(
        f"https://agenda.example.com:{server}/push/{path}", b"x", []
    )
    assert result.status == status
    assert result.retry_after == ("60" if path == "busy" else None)


async def test_post_never_follows_a_redirect(server: int, tls_files: dict[str, Path]) -> None:
    result = await client(tls_files, standard_dns()).post(
        f"https://agenda.example.com:{server}/push/hop", b"x", []
    )
    assert result.status == 307
    assert len(Handler.posted) == 1


async def test_post_to_a_private_address_is_never_sent(
    server: int, tls_files: dict[str, Path]
) -> None:
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).post(
            f"https://prive.example.com:{server}/push/ok", b"x", []
        )
    assert error.value.reason == "forbidden_address"
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).post("http://agenda.example.com/push/ok", b"x", [])
    assert error.value.reason == "invalid_url"
    assert Handler.posted == []


async def test_post_time_is_bounded(server: int, tls_files: dict[str, Path]) -> None:
    started = time.monotonic()
    with pytest.raises(OutboundError) as error:
        await client(tls_files, standard_dns()).post(
            f"https://agenda.example.com:{server}/push/slow",
            b"x",
            [],
            limits=FetchLimits(total_timeout_s=1.0),
        )
    assert error.value.reason == "timeout"
    assert time.monotonic() - started < 2.5


async def test_post_with_an_untrusted_certificate_is_refused(server: int) -> None:
    production = OutboundHttp(resolver=standard_dns(), address_policy=only_loopback_or_public)
    with pytest.raises(OutboundError) as error:
        await production.post(f"https://agenda.example.com:{server}/push/ok", b"x", [])
    assert error.value.reason == "tls"
