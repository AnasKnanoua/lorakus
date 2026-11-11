"""Cles d'API et codes de secours : secrets aleatoires dont seule l'empreinte est stockee."""

import hashlib
import hmac
import secrets
from typing import Final

API_KEY_PREFIX: Final = "lk_"
# Format : lk_<8 caracteres visibles>_<secret de 256 bits>. Le prefixe identifie la cle
# dans les listes et les journaux sans rien reveler du secret.
_VISIBLE_LENGTH: Final = 8
BACKUP_CODE_COUNT: Final = 10


def new_api_key() -> tuple[str, str]:
    """(prefixe visible, cle complete). La cle complete n'est montree qu'une fois."""
    visible = secrets.token_hex(_VISIBLE_LENGTH // 2)
    prefix = f"{API_KEY_PREFIX}{visible}"
    return prefix, f"{prefix}_{secrets.token_urlsafe(32)}"


def split_api_key(raw: str) -> str | None:
    """Prefixe d'une cle bien formee, ou None.

    Decoupage a position fixe : le secret (base64 URL) peut lui-meme contenir des « _ ».
    """
    head_length = len(API_KEY_PREFIX) + _VISIBLE_LENGTH
    head, separator, secret = (
        raw[:head_length],
        raw[head_length : head_length + 1],
        raw[head_length + 1 :],
    )
    if (
        not head.startswith(API_KEY_PREFIX)
        or not all(c in "0123456789abcdef" for c in head[len(API_KEY_PREFIX) :])
        or separator != "_"
        or len(secret) != 43
    ):
        return None
    return head


def digest(value: str) -> bytes:
    """Empreinte SHA-256 (secrets aleatoires de 64 bits et plus : pas besoin d'Argon2)."""
    return hashlib.sha256(value.encode("utf-8")).digest()


def new_backup_codes() -> list[str]:
    """10 codes de 64 bits, affiches sous la forme xxxx-xxxx-xxxx-xxxx."""
    codes: list[str] = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = secrets.token_hex(8)
        codes.append("-".join(raw[i : i + 4] for i in range(0, 16, 4)))
    return codes


def normalize_backup_code(code: str) -> str:
    """Saisie tolerante : sans tirets, espaces ni majuscules."""
    return code.replace("-", "").replace(" ", "").strip().lower()


def constant_time_equal(left: bytes, right: bytes) -> bool:
    """Comparaison en temps constant (pas d'indice par la duree de la reponse)."""
    return hmac.compare_digest(left, right)
