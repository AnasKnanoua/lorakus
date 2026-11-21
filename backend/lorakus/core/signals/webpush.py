"""Web Push (ADR 0042) : chiffrement du message (RFC 8291) et identite VAPID (RFC 8292).

Une notification Web Push part du serveur vers le service de notification du navigateur
(Google pour Chrome, Mozilla pour Firefox, Apple pour Safari), qui la remet a l'appareil. Le
message est chiffre de bout en bout : le service la transporte sans pouvoir la lire.

- Chiffrement (RFC 8291, `aes128gcm` de la RFC 8188) : une cle ephemere par message, un
  secret partage ECDH avec la cle publique de l'appareil (`p256dh`), melange au secret
  d'authentification de l'abonnement (`auth`), puis AES-128-GCM.
- VAPID (RFC 8292) : chaque envoi porte un jeton signe par la cle privee de Lorakus ; le
  service refuse un envoi qui ne correspond pas a la cle publique donnee a l'abonnement.

Ecrit sur `cryptography` (deja une dependance) plutot qu'avec `pywebpush` : celle-ci envoie
par `requests`, hors de notre client sortant protege contre la SSRF, alors que l'adresse
d'envoi est fournie par le navigateur. Verifie par les vecteurs de test de la RFC 8291.

Aucune entree/sortie ici : des fonctions pures, et la liste des services autorises.
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_SIZE: Final = 4096
# Taille maximale d'un message chiffre acceptee par tous les services : 4 096 octets.
MAX_PAYLOAD_BYTES: Final = 3000
MAX_ENDPOINT_CHARS: Final = 1024
# Un jeton VAPID vaut 24 h au plus (RFC 8292) ; 12 h laissent de la marge aux horloges.
TOKEN_LIFETIME_S: Final = 12 * 3600

# Services de notification des navigateurs. Une adresse d'abonnement vient du navigateur :
# elle n'est acceptee que si son nom est l'un d'eux (exact, ou sous-domaine pour Windows).
PUSH_HOSTS: Final = frozenset(
    {
        "fcm.googleapis.com",  # Chrome, Edge sur Android, navigateurs Chromium
        "updates.push.services.mozilla.com",  # Firefox
        "web.push.apple.com",  # Safari
    }
)
PUSH_HOST_SUFFIXES: Final = (".notify.windows.com",)  # Edge sur Windows


class InvalidSubscriptionError(ValueError):
    """Abonnement refuse ; le message est lisible par l'utilisateur."""


def b64url_decode(text: str) -> bytes:
    """Base64 « URL » avec ou sans remplissage (format des navigateurs)."""
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise InvalidSubscriptionError("Clé d'abonnement illisible.") from None


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def push_host(endpoint: str) -> str:
    """Nom du service d'une adresse d'abonnement valide (journalisable : jamais l'adresse)."""
    parts = urlsplit(endpoint)
    return (parts.hostname or "").lower()


def check_endpoint(endpoint: str) -> str:
    """L'adresse d'un abonnement, si elle mene a un service de notification connu."""
    if len(endpoint) > MAX_ENDPOINT_CHARS or any(c.isspace() for c in endpoint):
        raise InvalidSubscriptionError("Adresse d'abonnement invalide.")
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise InvalidSubscriptionError("Adresse d'abonnement invalide.") from None
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or len(parts.path) < 2
        or parts.fragment
    ):
        raise InvalidSubscriptionError("Adresse d'abonnement invalide.")
    if host not in PUSH_HOSTS and not any(host.endswith(s) for s in PUSH_HOST_SUFFIXES):
        raise InvalidSubscriptionError("Service de notification inconnu.")
    return endpoint


def load_device_key(p256dh: str) -> ec.EllipticCurvePublicKey:
    """Cle publique de l'appareil : un point non compresse de la courbe P-256."""
    raw = b64url_decode(p256dh)
    if len(raw) != 65 or raw[0] != 0x04:
        raise InvalidSubscriptionError("Clé d'abonnement invalide.")
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise InvalidSubscriptionError("Clé d'abonnement invalide.") from None


def check_auth_secret(auth: str) -> bytes:
    raw = b64url_decode(auth)
    if len(raw) != 16:
        raise InvalidSubscriptionError("Clé d'abonnement invalide.")
    return raw


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """Corps chiffre `aes128gcm` d'un message (un seul enregistrement).

    `salt` et `server_key` ne sont donnes que par les tests (vecteurs de la RFC 8291) : en
    service, ils sont tires au hasard a chaque message.
    """
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("message trop long pour une notification")
    device = load_device_key(p256dh)
    secret = check_auth_secret(auth)
    salt = os.urandom(16) if salt is None else salt
    ephemeral = server_key or ec.generate_private_key(ec.SECP256R1())
    device_raw = _public_bytes(device)
    server_raw = _public_bytes(ephemeral.public_key())

    shared = ephemeral.exchange(ec.ECDH(), device)
    # RFC 8291 §3.3 : IKM = HKDF(auth, ECDH, "WebPush: info" || 0 || cle appareil || cle serveur)
    prk_key = _hmac(secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + device_raw + server_raw + b"\x01")
    # RFC 8188 §2.2 : cle de contenu et nonce
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    # Un seul enregistrement : le delimiteur 0x02 marque le dernier (RFC 8188 §2).
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(server_raw)) + server_raw
    return header + ciphertext


@dataclass(frozen=True)
class VapidKeys:
    """Paire de cles VAPID de Lorakus (P-256). Le worker a la privee ; l'API, la publique."""

    private: ec.EllipticCurvePrivateKey

    @classmethod
    def from_hex(cls, private_hex: str, public_hex: str | None = None) -> "VapidKeys":
        """Cles de l'environnement (init-env.sh : 64 et 130 caracteres hexadecimaux) ; la
        publique, si elle est donnee, doit correspondre a la privee."""
        try:
            scalar = int(private_hex, 16)
            if len(private_hex) != 64:
                raise ValueError
            key = ec.derive_private_key(scalar, ec.SECP256R1())
        except ValueError:
            raise ValueError("cle VAPID privee invalide (64 caracteres hexadecimaux)") from None
        keys = cls(key)
        if public_hex is not None and keys.public_hex != public_hex.lower():
            raise ValueError("les cles VAPID publique et privee ne vont pas ensemble")
        return keys

    @property
    def public_raw(self) -> bytes:
        return _public_bytes(self.private.public_key())

    @property
    def public_hex(self) -> str:
        return self.public_raw.hex()

    def authorization(self, endpoint: str, subject: str, now: float | None = None) -> str:
        """En-tete Authorization d'un envoi vers `endpoint` (RFC 8292 §3)."""
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(now if now is not None else time.time()) + TOKEN_LIFETIME_S,
            "sub": subject,
        }
        header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        body = b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header}.{body}".encode("ascii")
        der = self.private.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={header}.{body}.{signature},k={b64url(self.public_raw)}"


def public_key_for_browser(public_hex: str) -> str:
    """La cle publique au format attendu par `pushManager.subscribe` (base64 URL)."""
    raw = bytes.fromhex(public_hex)
    if len(raw) != 65 or raw[0] != 0x04:
        raise ValueError("cle VAPID publique invalide (130 caracteres hexadecimaux)")
    return b64url(raw)
