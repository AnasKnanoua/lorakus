"""Jetons de session : aleatoires, seule leur empreinte est stockee."""

import hashlib
import secrets
from typing import Final

# 32 octets aleatoires : impossible a deviner, meme avec un tres grand nombre d'essais.
TOKEN_BYTES: Final = 32
# Longueur exacte d'un jeton encode (base64 URL, sans remplissage).
TOKEN_LENGTH: Final = 43


def new_token() -> str:
    """Nouveau jeton de session, a remettre au client (cookie) et a ne jamais stocker."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    """Empreinte SHA-256 stockee en base.

    Un hachage rapide suffit ici, contrairement aux mots de passe : le jeton a deja
    256 bits d'aleatoire. Une fuite de la table ne donne aucun jeton utilisable.
    """
    return hashlib.sha256(token.encode("ascii")).digest()


def looks_like_token(value: str) -> bool:
    """Filtre les valeurs manifestement invalides avant toute requete en base."""
    return len(value) == TOKEN_LENGTH and value.isascii()
