"""Authentification cote API : cookie de session et dependance « utilisateur courant »."""

from datetime import UTC, datetime
from typing import Annotated, Final, cast

from fastapi import Depends, HTTPException, Request, Response, status

from lorakus.core.identity.service import CurrentUser, IdentityService, IssuedSession

# Prefixe __Host- : le navigateur refuse ce cookie s'il n'est pas Secure, s'il porte un
# attribut Domain ou si son Path n'est pas "/". Il ne peut donc ni etre pose par un
# sous-domaine, ni fuiter vers un autre site.
SESSION_COOKIE: Final = "__Host-lorakus_session"


def get_identity(request: Request) -> IdentityService:
    """Dependance : service d'identite de l'application."""
    return cast(IdentityService, request.app.state.identity)


def client_ip(request: Request) -> str | None:
    """Adresse du client. Aucun en-tete X-Forwarded-For n'est cru avant le proxy (P3)."""
    return request.client.host if request.client is not None else None


def set_session_cookie(response: Response, issued: IssuedSession) -> None:
    """Pose le cookie de session : HttpOnly, Secure, SameSite=Strict, Path=/."""
    max_age = int((issued.expires_at - datetime.now(UTC)).total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    """Efface le cookie (memes attributs, sinon le navigateur l'ignore)."""
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise."
)


async def current_user(
    request: Request, identity: Annotated[IdentityService, Depends(get_identity)]
) -> CurrentUser:
    """Dependance : utilisateur de la session, ou 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise UNAUTHENTICATED
    user = await identity.authenticate(token)
    if user is None:
        raise UNAUTHENTICATED
    return user
