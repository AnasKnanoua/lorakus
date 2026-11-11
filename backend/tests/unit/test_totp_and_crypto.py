"""TOTP (vecteurs de la RFC 6238), chiffrement des champs, formats des cles."""

import base64

import pytest

from lorakus.core.identity import keys, totp
from lorakus.core.identity.crypto import FieldCipher

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
KEY = "00" * 32


@pytest.mark.parametrize(
    ("unix_time", "expected"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_rfc6238_sha1_vectors(unix_time: int, expected: str) -> None:
    # La RFC donne 8 chiffres ; les applications en affichent 6 (les 6 derniers).
    assert totp.code_at(RFC_SECRET, totp.current_step(unix_time)) == expected


def test_code_is_accepted_one_step_around_and_never_twice() -> None:
    now = 1_700_000_000.0
    step = totp.current_step(now)
    for offset in (-1, 0, 1):
        assert (
            totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step + offset), now, None)
            == step + offset
        )
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step + 2), now, None) is None
    # Anti-rejeu : un pas deja utilise (ou plus ancien) est refuse.
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step), now, step) is None
    assert totp.matching_step(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now, step) is None
    assert totp.matching_step(RFC_SECRET, "12345", now, None) is None
    assert totp.matching_step(RFC_SECRET, "abcdef", now, None) is None


def test_provisioning_uri() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, "anas@example.com")
    assert uri.startswith("otpauth://totp/Lorakus%3Aanas%40example.com?")
    assert f"secret={RFC_SECRET}" in uri


def test_field_cipher_round_trip_and_context_binding() -> None:
    cipher = FieldCipher(KEY)
    sealed = cipher.encrypt(b"secret", b"user-a")
    assert sealed.startswith("v1:")
    assert "secret" not in sealed
    assert cipher.decrypt(sealed, b"user-a") == b"secret"
    with pytest.raises(ValueError, match="deplacee"):
        cipher.decrypt(sealed, b"user-b")
    with pytest.raises(ValueError, match="deplacee"):
        FieldCipher("11" * 32).decrypt(sealed, b"user-a")
    tampered = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
    with pytest.raises(ValueError):
        cipher.decrypt(tampered, b"user-a")


def test_field_cipher_rejects_malformed_keys() -> None:
    for bad in ("", "00" * 31, "zz" * 32, "00" * 33):
        with pytest.raises(ValueError):
            FieldCipher(bad)


def test_api_key_with_underscores_in_its_secret_is_parsed() -> None:
    # Le secret en base64 URL contient souvent des « _ » (bogue trouve par les tests).
    key = "lk_0123abcd_" + "a_b" * 14 + "c"
    assert keys.split_api_key(key) == "lk_0123abcd"
    for _ in range(200):
        prefix, secret = keys.new_api_key()
        assert keys.split_api_key(secret) == prefix


def test_api_key_format() -> None:
    prefix, secret = keys.new_api_key()
    assert secret.startswith(prefix + "_")
    assert keys.split_api_key(secret) == prefix
    for bad in ("", "lk_abc", secret + "x", "xx" + secret[2:], prefix):
        assert keys.split_api_key(bad) is None


def test_backup_codes() -> None:
    codes = keys.new_backup_codes()
    assert len(codes) == len(set(codes)) == 10
    assert keys.normalize_backup_code(" ABCD-ef01 2345-6789 ") == "abcdef0123456789"
