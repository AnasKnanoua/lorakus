"""Portees des cles d'API. Une cle ne peut faire que ce que ses portees autorisent.

Les modules declareront les leurs dans leur manifeste (PR « systeme de modules ») ;
en attendant, la liste est fermee.
"""

from typing import Final

KNOWN_SCOPES: Final[dict[str, str]] = {
    "inbox:write": "Deposer des elements dans la boite de reception (partage depuis le telephone)",
    "usage:write": "Envoyer des donnees d'usage (application Android, extension navigateur)",
    "health:write": "Envoyer des donnees de sante (Health Connect)",
}
