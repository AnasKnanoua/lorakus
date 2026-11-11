"""Routes d'authentification : /api/v1/auth/..."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr

from lorakus.api.auth import (
    SESSION_COOKIE,
    clear_session_cookie,
    client_ip,
    current_user,
    get_identity,
    set_session_cookie,
)
from lorakus.core.identity.passwords import MAX_PASSWORD_LENGTH, WeakPasswordError
from lorakus.core.identity.service import (
    MAX_EMAIL_LENGTH,
    CurrentUser,
    IdentityService,
    InvalidCredentialsError,
    TooManyAttemptsError,
)

router = APIRouter(prefix="/v1/auth", tags=["authentification"])

# Un seul message pour un compte inconnu, inactif ou un mot de passe faux.
INVALID_CREDENTIALS = "Identifiants invalides."
TOO_MANY_ATTEMPTS = "Trop de tentatives. Reessayez plus tard."


class LoginRequest(BaseModel):
    """Corps de la connexion."""

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class PasswordChangeRequest(BaseModel):
    """Corps du changement de mot de passe."""

    current_password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class MeResponse(BaseModel):
    """Utilisateur connecte."""

    id: UUID
    email: str
    role: str


Identity = Annotated[IdentityService, Depends(get_identity)]
User = Annotated[CurrentUser, Depends(current_user)]


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    body: LoginRequest, request: Request, response: Response, identity: Identity
) -> None:
    """Ouvre une session et pose le cookie."""
    try:
        issued = await identity.login(
            body.email, body.password.get_secret_value(), client_ip(request)
        )
    except TooManyAttemptsError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ATTEMPTS) from None
    except InvalidCredentialsError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS) from None
    set_session_cookie(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, identity: Identity, user: User) -> None:
    """Ferme la session courante."""
    await identity.logout(user, request.cookies.get(SESSION_COOKIE, ""))
    clear_session_cookie(response)


@router.get("/me")
async def me(user: User) -> MeResponse:
    """Utilisateur connecte."""
    return MeResponse(id=user.id, email=user.email, role=user.role)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    identity: Identity,
    user: User,
) -> None:
    """Change le mot de passe ; toutes les sessions sont revoquees, une nouvelle est ouverte."""
    try:
        issued = await identity.change_password(
            user,
            body.current_password.get_secret_value(),
            body.new_password.get_secret_value(),
            client_ip(request),
        )
    except WeakPasswordError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except InvalidCredentialsError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS) from None
    set_session_cookie(response, issued)
