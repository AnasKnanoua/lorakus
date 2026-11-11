"""Chiffrement de champs en base (AES-256-GCM), avec une cle hors de la base.

Une copie de la base (sauvegarde, fuite) ne suffit donc pas a lire ces champs.
Chaque valeur est liee a un contexte (l'identifiant de l'utilisateur) : copier le
secret d'un compte sur un autre le rend indechiffrable.
"""

import base64
import os
import re
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lorakus.settings import Settings

VERSION: Final = "v1"
_KEY_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class FieldEncryptionUnavailableError(RuntimeError):
    """Aucune cle de chiffrement configuree (LORAKUS_FIELD_ENCRYPTION_KEY)."""


class FieldCipher:
    """Chiffre et dechiffre de petites valeurs (secrets TOTP)."""

    def __init__(self, key_hex: str) -> None:
        if not _KEY_PATTERN.fullmatch(key_hex):
            raise ValueError("LORAKUS_FIELD_ENCRYPTION_KEY : 64 caracteres hexadecimaux attendus")
        self._aead = AESGCM(bytes.fromhex(key_hex))

    @classmethod
    def from_settings(cls, settings: Settings) -> "FieldCipher | None":
        """None si la cle est absente, ce qui n'est admis qu'en developpement et en test."""
        key = settings.field_encryption_key.get_secret_value()
        if not key:
            if settings.environment in ("staging", "production"):
                raise ValueError("LORAKUS_FIELD_ENCRYPTION_KEY manquante")
            return None
        return cls(key)

    def encrypt(self, plaintext: bytes, context: bytes) -> str:
        """Valeur chiffree, prefixee de la version du format."""
        nonce = os.urandom(12)
        sealed = self._aead.encrypt(nonce, plaintext, context)
        return f"{VERSION}:" + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, value: str, context: bytes) -> bytes:
        """Valeur en clair ; ValueError si elle a ete modifiee ou deplacee."""
        version, _, payload = value.partition(":")
        if version != VERSION:
            raise ValueError(f"format de chiffrement inconnu : {version}")
        raw = base64.urlsafe_b64decode(payload)
        try:
            return self._aead.decrypt(raw[:12], raw[12:], context)
        except InvalidTag as error:
            raise ValueError("valeur chiffree invalide ou deplacee") from error
