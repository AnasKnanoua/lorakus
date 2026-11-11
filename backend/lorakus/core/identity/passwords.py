"""Hachage des mots de passe : Argon2id.

Parametres : ceux d'argon2-cffi par defaut (profil "faible memoire" de la RFC 9106 :
temps 3, memoire 64 Mio, parallelisme 4), au-dessus du minimum OWASP (temps 2,
memoire 19 Mio, parallelisme 1). Si on les durcit plus tard, chaque mot de passe
est re-hache automatiquement a la connexion suivante (needs_rehash).

Le calcul (environ 50 ms) part dans un thread : la boucle asynchrone reste libre.
"""

import secrets
from dataclasses import dataclass
from functools import cache
from typing import Final

import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH: Final = 12
MAX_PASSWORD_LENGTH: Final = 1024

# Minimum OWASP pour Argon2id (Password Storage Cheat Sheet).
OWASP_MIN_MEMORY_KIB: Final = 19 * 1024
OWASP_MIN_TIME_COST: Final = 2

HASHER: Final = PasswordHasher()


@dataclass(frozen=True)
class Verification:
    """Resultat d'une verification de mot de passe."""

    ok: bool
    needs_rehash: bool = False


class WeakPasswordError(ValueError):
    """Mot de passe refuse par la politique (longueur)."""


def check_policy(password: str) -> None:
    """Longueur seulement (recommandation NIST) : pas de regles de composition."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Au moins {MIN_PASSWORD_LENGTH} caracteres.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(f"Au plus {MAX_PASSWORD_LENGTH} caracteres.")


@cache
def dummy_hash() -> str:
    """Hachage d'un mot de passe aleatoire, aux memes parametres que les vrais.

    Verifie quand le compte n'existe pas : la reponse prend alors le meme temps
    que pour un compte existant, et ne revele pas son existence.
    """
    return HASHER.hash(secrets.token_urlsafe(32))


def _hash(password: str) -> str:
    return HASHER.hash(password)


def _verify(stored_hash: str, password: str) -> Verification:
    try:
        HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return Verification(ok=False)
    return Verification(ok=True, needs_rehash=HASHER.check_needs_rehash(stored_hash))


async def hash_password(password: str) -> str:
    """Hache un mot de passe (dans un thread)."""
    return await anyio.to_thread.run_sync(_hash, password)


async def verify_password(stored_hash: str, password: str) -> Verification:
    """Verifie un mot de passe (dans un thread). Ne leve jamais d'exception."""
    return await anyio.to_thread.run_sync(_verify, stored_hash, password)
