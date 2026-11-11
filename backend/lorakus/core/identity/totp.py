"""Codes a usage unique bases sur le temps (TOTP, RFC 6238), compatibles avec les
applications d'authentification courantes : SHA-1, 6 chiffres, pas de 30 secondes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
from typing import Final
from urllib.parse import quote, urlencode

STEP_SECONDS: Final = 30
DIGITS: Final = 6
# Tolerance d'un pas avant et apres : horloge du telephone un peu decalee.
WINDOW: Final = 1
ISSUER: Final = "Lorakus"


def new_secret() -> str:
    """Secret de 160 bits, en base32 (le format attendu par les applications)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    """Code du pas donne (HOTP, RFC 4226)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(unix_time: float) -> int:
    return int(unix_time // STEP_SECONDS)


def matching_step(
    secret: str, code: str, unix_time: float, last_used_step: int | None
) -> int | None:
    """Pas correspondant au code, ou None. Un pas deja utilise est refuse (anti-rejeu)."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = current_step(unix_time)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """Adresse otpauth:// a afficher en QR code dans l'application d'authentification."""
    label = quote(f"{ISSUER}:{account}")
    query = urlencode(
        {
            "secret": secret,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"
