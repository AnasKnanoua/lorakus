"""Ce que le client sortant accepte : adresses publiques et URL HTTPS bien formees (PR 45).

Defense contre la SSRF (Server-Side Request Forgery) : une adresse donnee par un utilisateur
ou par une redirection ne doit jamais faire parler le serveur a lui-meme, au reseau Docker,
au reseau du fournisseur de cloud ni a son service de metadonnees (169.254.169.254, qui
donne les identifiants de la machine).

Deux barrieres independantes :
1. le NOM : HTTPS seul, pas d'identifiants dans l'URL, un vrai nom de domaine (jamais une
   adresse IP ecrite en clair ou deguisee : 2130706433, 0x7f000001, 0177.0.0.1, 127.1 sont
   tous resolus en 127.0.0.1 par getaddrinfo), pas de nom reserve (localhost, .internal...) ;
2. l'ADRESSE obtenue par la resolution : publique, apres avoir deballe les formes IPv6 qui
   transportent une IPv4 (::ffff:a.b.c.d, ::a.b.c.d, 6to4, NAT64). Le module ipaddress de
   Python juge « globales » ::127.0.0.1, 64:ff9b::a00:1 (soit 10.0.0.1) et les adresses
   de multidiffusion : son is_global ne suffit pas.
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

MAX_URL_CHARS: Final = 2048
_LABEL: Final = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# Le dernier label d'un vrai nom est alphabetique (ou IDN) : aucune IP deguisee n'y passe.
_TLD: Final = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
# Noms reserves ou internes (RFC 6761, 6762, 8375, 9476 ; .internal reserve par l'ICANN).
_RESERVED_SUFFIXES: Final = (
    "localhost",
    "local",
    "internal",
    "invalid",
    "test",
    "onion",
    "alt",
    "home.arpa",
)
_FORBIDDEN_URL_CHARS: Final = re.compile(r"[\s\\\x00-\x1f\x7f]")
# Ecritures numeriques d'une IPv4 que getaddrinfo accepte (decimal, octal, hexadecimal, court).
_NUMERIC_HOST: Final = re.compile(r"^(?=.*[0-9])[0-9a-fx.]+$")

# Reseaux refuses en plus de « non global » (redondance voulue : un changement du module
# ipaddress ne doit pas ouvrir une breche). Multidiffusion et 6to4 relais compris.
_DENIED: Final[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # partage (CGNAT ; metadonnees d'Alibaba)
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # liaison locale, metadonnees (Oracle, AWS...)
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),  # relais 6to4 (juge « global » par Python)
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),  # multidiffusion (jugee « globale » par Python)
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("100::/64"),
    ipaddress.ip_network("2001::/32"),  # Teredo : IPv4 du client masquee, refuse en bloc
    ipaddress.ip_network("2001:db8::/32"),
    ipaddress.ip_network("64:ff9b:1::/48"),  # NAT64 local
    ipaddress.ip_network("fc00::/7"),  # adresses uniques locales (fd00:ec2::254 d'AWS)
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("ff00::/8"),
)
_NAT64: Final = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE: Final = ipaddress.ip_network("::/96")


class InvalidUrlError(ValueError):
    """URL refusee avant toute connexion ; le message s'affiche a l'utilisateur."""


def embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """L'IPv4 que transporte une adresse IPv6 (mappee, compatible, 6to4, NAT64), sinon None."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address in _NAT64 or address in _IPV4_COMPATIBLE:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def is_public_address(address: IPAddress) -> bool:
    """Vrai seulement pour une adresse joignable sur Internet et sans sens local."""
    if isinstance(address, ipaddress.IPv6Address):
        inner = embedded_ipv4(address)
        if inner is not None:
            return is_public_address(inner)
    if any(address in network for network in _DENIED if network.version == address.version):
        return False
    return address.is_global and not address.is_multicast


def _check_host(raw: str) -> str:
    """Nom de domaine en ASCII minuscule, ou InvalidUrlError."""
    host = raw.rstrip(".")
    if not host:
        raise InvalidUrlError("l'adresse n'a pas de nom de domaine")
    if host.startswith("[") or ":" in host:
        raise InvalidUrlError("utilise un nom de domaine, pas une adresse IP")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise InvalidUrlError("nom de domaine invalide") from None
    try:
        ipaddress.ip_address(ascii_host)
    except ValueError:
        pass
    else:
        raise InvalidUrlError("utilise un nom de domaine, pas une adresse IP")
    for suffix in _RESERVED_SUFFIXES:
        if ascii_host == suffix or ascii_host.endswith("." + suffix):
            raise InvalidUrlError("ce nom de domaine est reserve a un reseau local")
    labels = ascii_host.split(".")
    if not _TLD.match(labels[-1]):
        if _NUMERIC_HOST.match(ascii_host):
            # 2130706433, 0x7f000001, 0177.0.0.1, 127.1 : une adresse IP deguisee en nom.
            raise InvalidUrlError("utilise un nom de domaine, pas une adresse IP")
        raise InvalidUrlError("nom de domaine invalide")
    if len(ascii_host) > 253 or len(labels) < 2 or not all(_LABEL.match(x) for x in labels):
        raise InvalidUrlError("nom de domaine invalide")
    return ascii_host


@dataclass(frozen=True)
class SafeUrl:
    """URL HTTPS validee. Ne jamais la journaliser en entier : elle peut porter un secret."""

    host: str
    port: int
    target: str  # chemin et requete, tels que recus (deja encodes)

    @property
    def text(self) -> str:
        port = "" if self.port == 443 else f":{self.port}"
        return f"https://{self.host}{port}{self.target}"


def parse_public_url(raw: str) -> SafeUrl:
    """Valide une URL donnee par l'utilisateur ou par une redirection (sans reseau)."""
    if len(raw) > MAX_URL_CHARS:
        raise InvalidUrlError(f"adresse trop longue ({MAX_URL_CHARS} caracteres au plus)")
    if _FORBIDDEN_URL_CHARS.search(raw):
        raise InvalidUrlError("l'adresse contient des espaces ou des caracteres interdits")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise InvalidUrlError("adresse invalide") from None
    if parts.scheme.lower() != "https":
        raise InvalidUrlError("l'adresse doit commencer par https://")
    if "@" in parts.netloc:
        raise InvalidUrlError("l'adresse ne doit pas contenir d'identifiants")
    host = _check_host(parts.hostname or "")
    if port == 0:
        raise InvalidUrlError("port invalide")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return SafeUrl(host=host, port=port or 443, target=target)


def display_hint(url: SafeUrl) -> str:
    """Rappel affichable d'une adresse secrete : le domaine seul. Aucune partie du chemin
    (le jeton secret y est parfois en dernier segment, ex. https://h.example/ical/<jeton>)."""
    return f"{url.host}/…"
