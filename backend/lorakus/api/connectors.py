"""Acces aux services des connecteurs depuis les routes des modules (PR 45)."""

from typing import cast

from fastapi import HTTPException, Request, status

from lorakus.core.identity.crypto import FieldCipher


def get_connector_cipher(request: Request) -> FieldCipher:
    """Dependance FastAPI : chiffrement des secrets des connecteurs (adresses ICS...).

    503 si la cle est absente (developpement seulement : ailleurs, l'API ne demarre pas)."""
    cipher = cast(FieldCipher | None, request.app.state.connector_cipher)
    if cipher is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Chiffrement indisponible : LORAKUS_CONNECTOR_ENCRYPTION_KEY absente.",
        )
    return cipher
