"""Client HTTP sortant du Core, protege contre la SSRF (PR 45).

Seul chemin par lequel Lorakus va chercher une ressource a une adresse fournie par un
utilisateur (abonnement ICS aujourd'hui). Les modules ne creent jamais leur propre client.

Pour chaque saut (adresse de depart, puis chaque redirection) :
1. l'URL est revalidee (policy.parse_public_url : HTTPS seul, vrai nom de domaine) ;
2. le nom est resolu UNE fois et TOUTES ses adresses doivent etre publiques ;
3. la connexion TCP vise l'une de CES adresses (jamais une nouvelle resolution : un DNS qui
   repondrait autre chose a la seconde question, « DNS rebinding », n'a pas de prise) ;
   le TLS verifie le certificat du NOM d'origine (SNI et verification d'hote) ;
4. reponse bornee : taille (Content-Length puis octets recus, decompression comprise),
   delais de connexion et de lecture, delai total, nombre de redirections.

Aucun proxy ni variable d'environnement (HTTPS_PROXY, .netrc), aucun cookie, aucune
redirection automatique. Jamais l'URL complete dans un journal : elle porte souvent un jeton.
"""

import ipaddress
import socket
import ssl
import zlib
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast
from urllib.parse import urljoin

import anyio
import httpcore2
import structlog

from lorakus.core.outbound.policy import (
    InvalidUrlError,
    IPAddress,
    SafeUrl,
    is_public_address,
    parse_public_url,
)

log = structlog.get_logger("lorakus.outbound")

Reason = Literal[
    "invalid_url",
    "forbidden_address",
    "dns",
    "connect",
    "tls",
    "timeout",
    "too_large",
    "too_many_redirects",
    "http_status",
    "encoding",
    "protocol",
]

# Messages pour l'utilisateur (tutoiement), sans detail technique ni adresse.
MESSAGES: Final[dict[str, str]] = {
    "invalid_url": "L'adresse est invalide.",
    "forbidden_address": "Cette adresse mène à un réseau privé : elle est refusée.",
    "dns": "Le nom de domaine est introuvable.",
    "connect": "Le serveur ne répond pas.",
    "tls": "Le certificat HTTPS du serveur n'est pas valide.",
    "timeout": "Le serveur a mis trop de temps à répondre.",
    "too_large": "Le fichier est trop gros.",
    "too_many_redirects": "Trop de redirections.",
    "http_status": "Le serveur a refusé la demande.",
    "encoding": "Le serveur a envoyé une réponse illisible.",
    "protocol": "Le serveur a envoyé une réponse illisible.",
}
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})


class OutboundError(Exception):
    """Echec d'un appel sortant. `reason` est stable (statut enregistre, metriques)."""

    def __init__(self, reason: Reason, detail: str = "", status: int | None = None) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: Reason = reason
        self.status = status

    @property
    def message(self) -> str:
        if self.reason == "http_status" and self.status is not None:
            return f"Le serveur a refusé la demande (code {self.status})."
        return MESSAGES[self.reason]


@dataclass(frozen=True)
class FetchLimits:
    """Bornes d'un appel. Le delai total couvre resolution, redirections et lecture."""

    max_bytes: int = 4 * 1024 * 1024
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    total_timeout_s: float = 25.0
    max_redirects: int = 3


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    status: int
    content_type: str | None
    host: str  # domaine de la reponse finale (journalisable)
    redirects: int


Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
AddressPolicy = Callable[[IPAddress], bool]


async def system_resolver(host: str, port: int) -> Sequence[str]:
    """Adresses du nom, dans l'ordre du systeme (sans doublon)."""
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in seen:
            seen.append(address)
    return seen


class _PinnedBackend(httpcore2.AsyncNetworkBackend):
    """Ouvre la connexion vers les adresses deja verifiees, jamais vers une nouvelle
    resolution du nom ; refuse tout autre nom que celui annonce."""

    def __init__(self, host: str, addresses: Sequence[str]) -> None:
        self._host = host
        self._addresses = tuple(addresses)
        self._inner = cast(httpcore2.AsyncNetworkBackend, httpcore2.AnyIOBackend())

    async def connect_tcp(  # signature imposee par httpcore2
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if host != self._host:
            raise httpcore2.ConnectError("hote inattendu")
        failure: Exception = httpcore2.ConnectError("aucune adresse")
        for address in self._addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as error:
                failure = error
        raise failure

    async def connect_unix_socket(  # signature imposee par httpcore2
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        raise httpcore2.ConnectError("socket unix interdite")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _Decoder:
    """Corps decode (identity, gzip ou deflate) et borne : une bombe de decompression
    s'arrete a la limite, jamais apres."""

    def __init__(self, encoding: str, limit: int) -> None:
        self._limit = limit
        self._size = 0
        self._parts: list[bytes] = []
        if encoding in ("", "identity"):
            self._zlib = None
        elif encoding in ("gzip", "x-gzip"):
            self._zlib = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            self._zlib = zlib.decompressobj()
        else:
            raise OutboundError("encoding", encoding[:20])

    def _keep(self, data: bytes) -> None:
        self._size += len(data)
        if self._size > self._limit:
            raise OutboundError("too_large")
        self._parts.append(data)

    def feed(self, chunk: bytes) -> None:
        if self._zlib is None:
            self._keep(chunk)
            return
        data = chunk
        try:
            while data:
                # Jamais plus que ce qui reste permis (+1 pour voir le depassement).
                out = self._zlib.decompress(data, self._limit - self._size + 1)
                self._keep(out)
                data = self._zlib.unconsumed_tail
        except zlib.error:
            raise OutboundError("encoding", "flux compresse invalide") from None

    def finish(self) -> bytes:
        if self._zlib is not None:
            try:
                self._keep(self._zlib.flush())
            except zlib.error:
                raise OutboundError("encoding", "flux compresse invalide") from None
        return b"".join(self._parts)


def _header(headers: Sequence[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None


def _translate(error: Exception) -> OutboundError:
    """Erreur de httpcore ou de TLS traduite en raison stable (ou relancee telle quelle)."""
    if isinstance(error, OutboundError):
        return error
    if isinstance(error, httpcore2.TimeoutException):
        return OutboundError("timeout")
    if isinstance(error, (httpcore2.ConnectError, httpcore2.ReadError, httpcore2.WriteError)):
        if isinstance(error.__cause__ or error.__context__, ssl.SSLError):
            return OutboundError("tls")
        return OutboundError("connect")
    if isinstance(error, ssl.SSLError):
        return OutboundError("tls")
    if isinstance(error, (httpcore2.ProtocolError, httpcore2.UnsupportedProtocol)):
        return OutboundError("protocol")
    raise error


def _timeouts(bounds: FetchLimits) -> dict[str, float]:
    return {
        "connect": bounds.connect_timeout_s,
        "read": bounds.read_timeout_s,
        "write": bounds.read_timeout_s,
        "pool": bounds.connect_timeout_s,
    }


def _target(url: SafeUrl) -> httpcore2.URL:
    return httpcore2.URL(
        scheme=b"https", host=url.host.encode("ascii"), port=url.port, target=url.target
    )


@dataclass(frozen=True)
class PostResult:
    """Issue d'un POST : le statut tel que le serveur l'a donne (jamais suivi)."""

    status: int
    host: str
    retry_after: str | None = None
    body: bytes = b""  # seulement si l'appelant l'a demande (keep_body)


# Un POST ne lit de la reponse que de quoi la consommer : c'est le statut qui compte.
POST_LIMITS: Final = FetchLimits(
    max_bytes=64 * 1024, connect_timeout_s=5.0, read_timeout_s=10.0, total_timeout_s=15.0
)


class OutboundHttp:
    """Client sortant. Une instance par processus ; sans etat entre deux appels."""

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        ssl_context: ssl.SSLContext | None = None,
        address_policy: AddressPolicy = is_public_address,
        user_agent: str = "Lorakus/1 (+https://app.lorakus.app)",
    ) -> None:
        self._resolve = resolver
        self._policy = address_policy
        self._user_agent = user_agent
        context = ssl_context or httpcore2.default_ssl_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._ssl = context

    @property
    def address_policy(self) -> AddressPolicy:
        return self._policy

    async def _addresses(self, url: SafeUrl) -> list[str]:
        try:
            raw = await self._resolve(url.host, url.port)
        except OSError:
            raise OutboundError("dns", url.host) from None
        if not raw:
            raise OutboundError("dns", url.host)
        checked: list[str] = []
        for text in raw:
            try:
                address = ipaddress.ip_address(text.split("%", 1)[0])
            except ValueError:
                raise OutboundError("dns", url.host) from None
            # Une seule adresse interdite suffit a refuser le nom : un domaine qui annonce a
            # la fois une adresse publique et une adresse privee ne merite pas confiance.
            if not self._policy(address):
                raise OutboundError("forbidden_address", url.host)
            checked.append(str(address))
        return checked

    def _pool(self, url: SafeUrl, addresses: Sequence[str]) -> httpcore2.AsyncConnectionPool:
        return httpcore2.AsyncConnectionPool(
            ssl_context=self._ssl,
            network_backend=_PinnedBackend(url.host, addresses),
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
        )

    async def post(
        self,
        url: str,
        body: bytes,
        headers: Sequence[tuple[str, str]],
        *,
        limits: FetchLimits = POST_LIMITS,
        keep_body: bool = False,
    ) -> PostResult:
        """POST unique (Web Push, ADR 0042) : memes controles qu'un GET pour l'adresse, aucune
        redirection suivie (une redirection est rendue comme un statut), aucune reprise.

        Le statut est rendu quel qu'il soit : c'est a l'appelant de savoir ce que 404 ou 429
        veulent dire pour lui. Seules les pannes de transport levent OutboundError.
        `keep_body` : la reponse est gardee (API Telegram), jusqu'a `limits.max_bytes` ; au-dela,
        OutboundError("too_large"). Sinon elle est lue puis ignoree.
        """
        try:
            safe = parse_public_url(url)
        except InvalidUrlError as error:
            raise OutboundError("invalid_url", str(error)) from None
        sent = [
            (b"User-Agent", self._user_agent.encode("ascii")),
            (b"Content-Length", str(len(body)).encode("ascii")),
            (b"Connection", b"close"),
            *((key.encode("ascii"), value.encode("ascii")) for key, value in headers),
        ]
        try:
            with anyio.fail_after(limits.total_timeout_s):
                addresses = await self._addresses(safe)
                pool = self._pool(safe, addresses)
                async with (
                    pool,
                    pool.stream(
                        "POST",
                        _target(safe),
                        headers=sent,
                        content=body,
                        extensions={"timeout": _timeouts(limits)},
                    ) as r,
                ):
                    read = 0
                    kept: list[bytes] = []
                    async for chunk in r.aiter_stream():
                        read += len(chunk)
                        if read > limits.max_bytes:
                            if keep_body:
                                raise OutboundError("too_large")
                            break  # reponse trop longue : on n'en a pas besoin
                        if keep_body:
                            kept.append(chunk)
                    retry_after = _header(r.headers, b"retry-after")
                    log.info("outbound_post", host=safe.host, status=r.status)
                    return PostResult(r.status, safe.host, retry_after, b"".join(kept))
        except TimeoutError:
            raise OutboundError("timeout") from None
        except Exception as error:
            raise _translate(error) from None

    async def get(
        self, url: str, *, limits: FetchLimits | None = None, accept: str = "*/*"
    ) -> FetchResult:
        """GET borne, redirections suivies et revalidees a chaque saut."""
        bounds = limits or FetchLimits()
        try:
            with anyio.fail_after(bounds.total_timeout_s):
                return await self._get(url, bounds, accept)
        except TimeoutError:
            raise OutboundError("timeout") from None

    async def _get(self, raw_url: str, bounds: FetchLimits, accept: str) -> FetchResult:
        current = raw_url
        for hop in range(bounds.max_redirects + 1):
            try:
                url = parse_public_url(current)
            except InvalidUrlError as error:
                raise OutboundError("invalid_url", str(error)) from None
            addresses = await self._addresses(url)
            location = await self._one(url, addresses, bounds, accept)
            if isinstance(location, FetchResult):
                log.info("outbound_fetch", host=url.host, status=location.status, hops=hop)
                return FetchResult(
                    location.body, location.status, location.content_type, url.host, hop
                )
            current = urljoin(url.text, location)
        raise OutboundError("too_many_redirects")

    async def _one(
        self, url: SafeUrl, addresses: Sequence[str], bounds: FetchLimits, accept: str
    ) -> FetchResult | str:
        """Un saut : la reponse finale, ou l'adresse de redirection (non suivie ici)."""
        headers = [
            (b"User-Agent", self._user_agent.encode("ascii")),
            (b"Accept", accept.encode("ascii")),
            (b"Accept-Encoding", b"gzip, identity"),
            (b"Connection", b"close"),
        ]
        pool = self._pool(url, addresses)
        try:
            async with (
                pool,
                pool.stream(
                    "GET", _target(url), headers=headers, extensions={"timeout": _timeouts(bounds)}
                ) as r,
            ):
                if r.status in _REDIRECTS:
                    location = _header(r.headers, b"location")
                    if not location:
                        raise OutboundError("protocol", "redirection sans destination")
                    return location
                if not 200 <= r.status < 300:
                    raise OutboundError("http_status", status=r.status)
                declared = _header(r.headers, b"content-length")
                if declared is not None and declared.isdigit() and int(declared) > bounds.max_bytes:
                    raise OutboundError("too_large")
                encoding = (_header(r.headers, b"content-encoding") or "").lower()
                decoder = _Decoder(encoding, bounds.max_bytes)
                async for chunk in r.aiter_stream():
                    decoder.feed(chunk)
                body = decoder.finish()
                return FetchResult(body, r.status, _header(r.headers, b"content-type"), "", 0)
        except Exception as error:
            raise _translate(error) from None
