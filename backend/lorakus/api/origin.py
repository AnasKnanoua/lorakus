"""Controle de l'origine des requetes d'ecriture (protection CSRF en profondeur).

Le cookie de session est deja SameSite=Strict : un autre site ne peut pas l'envoyer. Ce
controle ajoute une seconde barriere, independante du navigateur : toute requete qui modifie
des donnees (POST, PUT, PATCH, DELETE) et qui porte un en-tete Origin ou Sec-Fetch-Site doit
venir de l'interface de Lorakus. Un client sans navigateur (script, cle d'API) n'envoie aucun
de ces en-tetes : il passe, car il ne peut pas utiliser le cookie de quelqu'un d'autre.
"""

import json
from typing import Final

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from lorakus.observability.metrics import ORIGIN_REFUSED

SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
# Sec-Fetch-Site : envoye par tous les navigateurs recents. "same-site" (un sous-domaine
# voisin, ex. staging.lorakus.app) est refuse comme "cross-site".
ALLOWED_FETCH_SITES: Final = frozenset({"same-origin", "none"})

REFUSED_BODY: Final = json.dumps(
    {"detail": {"code": "origin_refused", "message": "Origine de la requete refusee."}}
).encode()

log = structlog.stdlib.get_logger("lorakus.http")


def origin_allowed(
    method: str, origin: str | None, fetch_site: str | None, allowed: frozenset[str]
) -> bool:
    """Decision pure (testee a part) : True si la requete peut continuer."""
    if method.upper() in SAFE_METHODS:
        return True
    if fetch_site is not None and fetch_site.lower() not in ALLOWED_FETCH_SITES:
        return False
    if origin is None:
        return True
    return origin in allowed  # "null" (iframe isolee, redirection) n'y figure jamais


class OriginCheckMiddleware:
    """Refuse (403) une ecriture sous /api venant d'une autre origine."""

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = str(scope.get("method", "GET"))
        if origin_allowed(
            method, headers.get("origin"), headers.get("sec-fetch-site"), self.allowed
        ):
            await self.app(scope, receive, send)
            return
        ORIGIN_REFUSED.inc()
        # L'origine est journalisee tronquee : elle vient du client.
        log.warning("origin_refused", method=method, origin=headers.get("origin", "")[:100])
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(REFUSED_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": REFUSED_BODY})
