"""Capture rapide (P5, scenario 5) : un texte venu d'un canal externe (le bot Telegram) et
range par le module qui le declare dans son manifeste (`capture`), la boite a idees de
`projects` aujourd'hui.

Le Core recoit le message, retrouve l'utilisateur et appelle la capture du module, sous la RLS
de cet utilisateur ; il ne connait pas le module (aucun import). Le module rend la phrase de
confirmation, ou leve CaptureRefusedError avec la raison lisible (boite pleine, doublon...).

Le texte capture est une donnee externe : le module l'enregistre avec sa provenance et le
presente toujours au modele a travers inert() (ADR 0042, PR 54).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CaptureRequest:
    session: AsyncSession  # transaction de l'utilisateur (RLS)
    user_id: uuid.UUID
    text: str
    channel: str  # « telegram »


class CaptureRefusedError(Exception):
    """Capture refusee ; le message est montre tel quel a l'utilisateur."""


# Signature attendue de ModuleManifest.capture (type libre dans le manifeste) : la phrase de
# confirmation montree a l'utilisateur.
Capture = Callable[[CaptureRequest], Awaitable[str]]
