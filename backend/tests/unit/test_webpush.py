"""Web Push (ADR 0042) : chiffrement RFC 8291, jeton VAPID RFC 8292, services autorises.

Le chiffrement est verifie par le vecteur de test officiel de la RFC 8291 (annexe A), puis par
un dechiffrement independant ecrit ici a partir de la RFC (le cote navigateur).
"""

import base64
import hashlib
import hmac
import json
import os
from typing import cast

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lorakus.core.outbound import OutboundHttp, PostResult
from lorakus.core.signals.dispatch import WebPusher
from lorakus.core.signals.models import PushSubscriptionRow
from lorakus.core.signals.webpush import (
    MAX_PAYLOAD_BYTES,
    InvalidSubscriptionError,
    VapidKeys,
    b64url,
    b64url_decode,
    check_endpoint,
    encrypt,
    public_key_for_browser,
    push_host,
)

# RFC 8291, annexe A.
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
# Secret d'authentification de l'abonnement (« auth_secret » de la RFC).
SHARED = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
EXPECTED = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmY"
    "WAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexS"
    "gSxsj_Qulcy4a-fN"
)


def _key(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64url_decode(text), "big"), ec.SECP256R1())


def _raw(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _h(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def decrypt(body: bytes, device: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    """Le navigateur : dechiffrement d'un message aes128gcm (RFC 8188 et 8291)."""
    salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    assert record_size >= len(body)
    server_raw = body[21 : 21 + id_length]
    ciphertext = body[21 + id_length :]
    server = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_raw)
    shared = device.exchange(ec.ECDH(), server)
    ikm = _h(
        _h(auth, shared), b"WebPush: info\x00" + _raw(device.public_key()) + server_raw + b"\x01"
    )
    prk = _h(salt, ikm)
    cek = _h(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _h(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert padded.rstrip(b"\x00").endswith(b"\x02")  # dernier enregistrement
    return padded.rstrip(b"\x00")[:-1]


def test_matches_the_official_test_vector() -> None:
    body = encrypt(
        PLAINTEXT, UA_PUBLIC, SHARED, salt=b64url_decode(SALT), server_key=_key(AS_PRIVATE)
    )
    assert b64url(body) == EXPECTED
    assert decrypt(body, _key(UA_PRIVATE), b64url_decode(SHARED)) == PLAINTEXT


def test_each_message_has_its_own_key_and_salt() -> None:
    device = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    first = encrypt(b"{}", b64url(_raw(device.public_key())), b64url(auth))
    second = encrypt(b"{}", b64url(_raw(device.public_key())), b64url(auth))
    assert first[:16] != second[:16] and first[21:86] != second[21:86]
    assert decrypt(first, device, auth) == decrypt(second, device, auth) == b"{}"


def test_another_device_cannot_read_the_message() -> None:
    device, other = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    body = encrypt(b"secret", b64url(_raw(device.public_key())), b64url(auth))
    with pytest.raises(Exception):  # noqa: B017 (InvalidTag de cryptography)
        decrypt(body, other, auth)
    with pytest.raises(Exception):  # noqa: B017 (meme appareil, mauvais secret)
        decrypt(body, device, os.urandom(16))


def test_a_compressed_device_key_is_refused() -> None:
    """Un point compresse est valide pour la courbe, mais pas pour Web Push (65 octets)."""
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    compressed = key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    )
    with pytest.raises(InvalidSubscriptionError):
        encrypt(b"{}", b64url(compressed), SHARED)


def test_too_long_a_message_is_refused() -> None:
    with pytest.raises(ValueError):
        encrypt(b"x" * (MAX_PAYLOAD_BYTES + 1), UA_PUBLIC, SHARED)


@pytest.mark.parametrize(
    ("p256dh", "auth"),
    [
        ("pas une cle", SHARED),
        (b64url(b"\x04" + b"\x01" * 64), SHARED),  # pas un point de la courbe
        (b64url(b"\x03" + b"\x01" * 32), SHARED),  # point compresse
        (UA_PUBLIC, b64url(b"court")),
        (UA_PUBLIC, "!!!"),
    ],
)
def test_bad_device_keys_are_refused(p256dh: str, auth: str) -> None:
    with pytest.raises(InvalidSubscriptionError):
        encrypt(b"{}", p256dh, auth)


# -------------------------------------------------------------------- VAPID
def verify(header: str, public: bytes) -> dict[str, object]:
    token = header.removeprefix("vapid t=").split(",k=")[0]
    head, body, signature = token.split(".")
    raw = b64url_decode(signature)
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    key.verify(
        encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        f"{head}.{body}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )
    assert json.loads(b64url_decode(head)) == {"typ": "JWT", "alg": "ES256"}
    claims: dict[str, object] = json.loads(b64url_decode(body))
    return claims


def test_the_vapid_token_is_signed_for_the_push_service_only() -> None:
    keys = VapidKeys.from_hex(os.urandom(32).hex())
    header = keys.authorization(
        "https://fcm.googleapis.com/fcm/send/abc?x=1", "https://app.lorakus.app", now=1_000
    )
    assert header.endswith(",k=" + b64url(keys.public_raw))
    claims = verify(header, keys.public_raw)
    # L'audience est l'origine du service, jamais l'adresse d'abonnement (qui est secrete).
    assert claims == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_000 + 12 * 3600,
        "sub": "https://app.lorakus.app",
    }
    other = VapidKeys.from_hex(os.urandom(32).hex())
    with pytest.raises(Exception):  # noqa: B017 (InvalidSignature)
        verify(header, other.public_raw)


def test_vapid_keys_from_the_environment() -> None:
    private = os.urandom(32).hex()
    keys = VapidKeys.from_hex(private)
    assert VapidKeys.from_hex(private, keys.public_hex.upper()).public_hex == keys.public_hex
    assert public_key_for_browser(keys.public_hex) == b64url(keys.public_raw)
    with pytest.raises(ValueError, match="ne vont pas ensemble"):
        VapidKeys.from_hex(private, VapidKeys.from_hex(os.urandom(32).hex()).public_hex)
    for bad in ("", "zz" * 32, private[:-2], "00" * 32):
        with pytest.raises(ValueError):
            VapidKeys.from_hex(bad)
    with pytest.raises(ValueError):
        public_key_for_browser("04" + "00" * 10)


def test_keys_are_base64url_without_padding() -> None:
    assert b64url(b"\xff\xfe") == "__4"
    assert b64url_decode("__4") == b"\xff\xfe" == b64url_decode("__4=")
    assert base64.urlsafe_b64encode(b"\xff\xfe") == b"__4="


# ------------------------------------------------------------ services admis
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc:def",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
        "https://web.push.apple.com/QAbc",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
        "https://FCM.googleapis.com:443/fcm/send/x",
    ],
)
def test_known_push_services_are_accepted(endpoint: str) -> None:
    assert check_endpoint(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",  # pas HTTPS
        "https://fcm.googleapis.com.attaquant.fr/x",
        "https://attaquant.fr/fcm.googleapis.com",
        "https://evilnotify.windows.com/x",  # pas un sous-domaine
        "https://notify.windows.com/x",
        "https://fcm.googleapis.com:8443/x",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com/",
        "https://fcm.googleapis.com/x#frag",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/x",
        "https://fcm.googleapis.com/a b",
        "https://fcm.googleapis.com/" + "a" * 1100,
        "https://[::1]/x",
        "https://fcm.googleapis.com:99999/x",
    ],
)
def test_anything_else_is_refused(endpoint: str) -> None:
    with pytest.raises(InvalidSubscriptionError):
        check_endpoint(endpoint)


def test_only_the_service_name_is_ever_shown() -> None:
    assert push_host("https://FCM.googleapis.com/fcm/send/secret") == "fcm.googleapis.com"


# ------------------------------------------------------- envoi complet (worker)
class RecordingHttp:
    """Le service de notification, vu de l'exterieur : ce qu'il recoit."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    async def post(self, url: str, body: bytes, headers: list[tuple[str, str]]) -> PostResult:
        self.calls.append((url, body, dict(headers)))
        return PostResult(self.status, push_host(url))


@pytest.mark.anyio
async def test_the_worker_sends_an_encrypted_signed_notification() -> None:
    device_key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    device = PushSubscriptionRow(
        endpoint="https://updates.push.services.mozilla.com/wpush/v2/secret",
        p256dh=b64url(_raw(device_key.public_key())),
        auth=b64url(auth),
        label="Firefox",
    )
    keys = VapidKeys.from_hex(os.urandom(32).hex())
    http = RecordingHttp(410)
    pusher = WebPusher(keys, "https://app.lorakus.app", cast(OutboundHttp, http))
    payload = {"title": "À rendre demain", "body": "Rapport · jeudi", "url": "/today", "tag": "x"}
    assert await pusher.send(device, payload, 3600) == 410
    [(url, body, headers)] = http.calls
    assert url == device.endpoint
    assert json.loads(decrypt(body, device_key, auth)) == payload  # le service ne lit rien
    assert b"Rapport" not in body
    assert headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "3600"
    claims = verify(headers["Authorization"], keys.public_raw)
    assert claims["aud"] == "https://updates.push.services.mozilla.com"


@pytest.mark.anyio
async def test_the_worker_never_posts_to_an_unknown_service() -> None:
    http = RecordingHttp()
    pusher = WebPusher(VapidKeys.from_hex(os.urandom(32).hex()), "s", cast(OutboundHttp, http))
    device = PushSubscriptionRow(
        endpoint="https://169.254.169.254/latest", p256dh=UA_PUBLIC, auth=SHARED, label="x"
    )
    with pytest.raises(InvalidSubscriptionError):
        await pusher.send(device, {}, 60)
    assert http.calls == []
