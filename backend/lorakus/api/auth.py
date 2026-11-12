"""Authentification cote API : cookie de session et dependance « utilisateur courant »."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Final, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status

from lorakus.core.identity.service import ApiPrincipal, CurrentUser, IdentityService, IssuedSession
from lorakus.core.ratelimit.service import Limit, RateLimiter

# Prefixe __Host- : le navigateur refuse ce cookie s'il n'est pas Secure, s'il porte un
# attribut Domain ou si son Path n'est pas "/". Il ne peut donc ni etre pose par un
# sous-domaine, ni fuiter vers un autre site.
SESSION_COOKIE: Final = "__Host-lorakus_session"


def get_identity(request: Request) -> IdentityService:
    """Dependance : service d'identite de l'application."""
    return cast(IdentityService, request.app.state.identity)


def client_ip(request: Request) -> str | None:
    """Adresse du client.

    Derriere Caddy, uvicorn remplace l'adresse du proxy par celle du visiteur, lue dans
    X-Forwarded-For, mais seulement si la connexion vient de l'adresse fixe de Caddy
    (FORWARDED_ALLOW_IPS, compose.prod.yml). Tout autre appelant ne peut pas la falsifier.
    """
    return request.client.host if request.client is not None else None


SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class RequestLimits:
    """Limites par utilisateur appliquees a chaque requete authentifiee (PR 35)."""

    all_requests: Limit
    writes: Limit

    def for_method(self, method: str) -> tuple[Limit, ...]:
        if method.upper() in SAFE_METHODS:
            return (self.all_requests,)
        return (self.all_requests, self.writes)


async def enforce_rate_limit(request: Request, user_id: UUID) -> None:
    """429 avec Retry-After si l'utilisateur depasse son rythme de requetes."""
    limiter = cast(RateLimiter | None, getattr(request.app.state, "rate_limiter", None))
    limits = cast(RequestLimits | None, getattr(request.app.state, "request_limits", None))
    if limiter is None or limits is None:
        return  # application de test montee sans base
    decision = await limiter.hit(user_id, limits.for_method(request.method))
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "message": "Trop de requetes. Reessayez plus tard."},
            headers={"Retry-After": str(decision.retry_after)},
        )


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
    await enforce_rate_limit(request, user.id)
    return user


REAUTH_REQUIRED = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={
        "code": "reauth_required",
        "message": "Confirmez votre identite (POST /api/v1/auth/reauth).",
    },
)


async def recent_user(
    user: Annotated[CurrentUser, Depends(current_user)],
    identity: Annotated[IdentityService, Depends(get_identity)],
) -> CurrentUser:
    """Dependance des actions sensibles : preuve d'identite de moins de 10 minutes, ou 403."""
    if not identity.recently_authenticated(user):
        raise REAUTH_REQUIRED
    return user


def api_key(scope: str) -> Callable[..., Awaitable[ApiPrincipal]]:
    """Dependance : appelant authentifie par cle d'API (en-tete Bearer) ayant `scope`."""

    async def dependency(
        request: Request, identity: Annotated[IdentityService, Depends(get_identity)]
    ) -> ApiPrincipal:
        header = request.headers.get("authorization", "")
        scheme, _, raw = header.partition(" ")
        if scheme.lower() != "bearer" or not raw:
            raise UNAUTHENTICATED
        principal = await identity.authenticate_api_key(raw.strip(), client_ip(request))
        if principal is None:
            raise UNAUTHENTICATED
        await enforce_rate_limit(request, principal.user_id)
        if scope not in principal.scopes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Portee insuffisante pour cette cle.")
        return principal

    return dependency
