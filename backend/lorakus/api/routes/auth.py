"""Routes d'authentification : /api/v1/auth/..."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr

from lorakus.api.auth import (
    clear_session_cookie,
    client_ip,
    current_user,
    get_identity,
    recent_user,
    set_session_cookie,
)
from lorakus.core.identity.crypto import FieldEncryptionUnavailableError
from lorakus.core.identity.passwords import MAX_PASSWORD_LENGTH, WeakPasswordError
from lorakus.core.identity.scopes import KNOWN_SCOPES
from lorakus.core.identity.service import (
    MAX_API_KEY_DAYS,
    MAX_EMAIL_LENGTH,
    ConflictError,
    CurrentUser,
    IdentityService,
    InvalidCredentialsError,
    SecondFactorMandatoryError,
    SecondFactorRequiredError,
    SecondFactorSetupRequiredError,
    TooManyAttemptsError,
)

router = APIRouter(prefix="/v1/auth", tags=["authentification"])

# Un seul message pour un compte inconnu, inactif ou un mot de passe faux.
INVALID_CREDENTIALS = "Identifiants invalides."
TOO_MANY_ATTEMPTS = "Trop de tentatives. Reessayez plus tard."
# Production : un compte sans double authentification ne peut pas ouvrir de session.
# Elle s'active sur le serveur (python -m lorakus.cli enable-second-factor).
SECOND_FACTOR_SETUP_REQUIRED = {
    "code": "second_factor_setup_required",
    "message": (
        "Double authentification obligatoire : activez-la sur le serveur avant de vous connecter."
    ),
}
SECOND_FACTOR_MANDATORY = {
    "code": "second_factor_mandatory",
    "message": "La double authentification est obligatoire ici : elle ne peut pas etre desactivee.",
}
SECOND_FACTOR_REQUIRED = {
    "code": "second_factor_required",
    "message": "Code de double authentification (ou code de secours) requis.",
}

Identity = Annotated[IdentityService, Depends(get_identity)]
User = Annotated[CurrentUser, Depends(current_user)]
RecentUser = Annotated[CurrentUser, Depends(recent_user)]
Secret = Annotated[SecretStr, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]
Code = Annotated[str, Field(min_length=6, max_length=32)]


# ---------------------------------------------------------------------- modeles
class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    password: Secret
    second_factor: Code | None = None


class ReauthRequest(BaseModel):
    password: Secret
    second_factor: Code | None = None


class PasswordChangeRequest(BaseModel):
    current_password: Secret
    new_password: Secret


class MeResponse(BaseModel):
    id: UUID
    email: str
    role: str
    totp_enabled: bool


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TotpConfirmRequest(BaseModel):
    code: Code


class BackupCodesResponse(BaseModel):
    backup_codes: list[str]


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(min_length=1)
    expires_in_days: int = Field(ge=1, le=MAX_API_KEY_DAYS)


class ApiKeyResponse(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime | None = None
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str = Field(description="A copier maintenant : elle ne sera plus jamais affichee.")


class AuditEventResponse(BaseModel):
    occurred_at: datetime
    action: str
    outcome: str
    details: dict[str, object]


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS)


# ---------------------------------------------------------------------- session
@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    body: LoginRequest, request: Request, response: Response, identity: Identity
) -> None:
    """Ouvre une session et pose le cookie."""
    try:
        issued = await identity.login(
            body.email, body.password.get_secret_value(), client_ip(request), body.second_factor
        )
    except TooManyAttemptsError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ATTEMPTS) from None
    except SecondFactorRequiredError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SECOND_FACTOR_REQUIRED) from None
    except SecondFactorSetupRequiredError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, SECOND_FACTOR_SETUP_REQUIRED) from None
    except InvalidCredentialsError:
        raise _unauthorized() from None
    set_session_cookie(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, identity: Identity, user: User) -> None:
    """Ferme la session courante."""
    await identity.logout(user, client_ip(request))
    clear_session_cookie(response)


@router.get("/me")
async def me(user: User, identity: Identity) -> MeResponse:
    """Utilisateur connecte."""
    return MeResponse(
        id=user.id, email=user.email, role=user.role, totp_enabled=await identity.totp_enabled(user)
    )


@router.post("/reauth", status_code=status.HTTP_204_NO_CONTENT)
async def reauth(body: ReauthRequest, request: Request, identity: Identity, user: User) -> None:
    """Nouvelle preuve d'identite, valable 10 minutes pour les actions sensibles."""
    try:
        await identity.reauthenticate(
            user, body.password.get_secret_value(), body.second_factor, client_ip(request)
        )
    except TooManyAttemptsError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY_ATTEMPTS) from None
    except SecondFactorRequiredError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SECOND_FACTOR_REQUIRED) from None
    except InvalidCredentialsError:
        raise _unauthorized() from None


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
        raise _unauthorized() from None
    set_session_cookie(response, issued)


# ---------------------------------------------------------------------- double authentification
def _encryption_unavailable() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Chiffrement non configure (LORAKUS_FIELD_ENCRYPTION_KEY).",
    )


@router.post("/totp/setup")
async def totp_setup(identity: Identity, user: RecentUser) -> TotpSetupResponse:
    """Prepare la double authentification : a scanner, puis confirmer par un code."""
    try:
        secret, uri = await identity.totp_setup(user)
    except ConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    except FieldEncryptionUnavailableError:
        raise _encryption_unavailable() from None
    return TotpSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm")
async def totp_confirm(
    body: TotpConfirmRequest, request: Request, identity: Identity, user: RecentUser
) -> BackupCodesResponse:
    """Active la double authentification. Les codes de secours ne sont montres qu'une fois."""
    try:
        codes = await identity.totp_confirm(user, body.code, client_ip(request))
    except ConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    except InvalidCredentialsError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Code incorrect.") from None
    except FieldEncryptionUnavailableError:
        raise _encryption_unavailable() from None
    return BackupCodesResponse(backup_codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(request: Request, identity: Identity, user: RecentUser) -> None:
    """Desactive la double authentification et supprime les codes de secours.

    Refuse (409) la ou elle est obligatoire, c'est-a-dire en production.
    """
    try:
        await identity.totp_disable(user, client_ip(request))
    except SecondFactorMandatoryError:
        raise HTTPException(status.HTTP_409_CONFLICT, SECOND_FACTOR_MANDATORY) from None


@router.post("/totp/backup-codes")
async def regenerate_backup_codes(
    request: Request, identity: Identity, user: RecentUser
) -> BackupCodesResponse:
    """Remplace tous les codes de secours."""
    try:
        codes = await identity.regenerate_backup_codes(user, client_ip(request))
    except ConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    return BackupCodesResponse(backup_codes=codes)


# ---------------------------------------------------------------------- cles d'API
@router.get("/api-keys/scopes")
async def api_key_scopes(_user: User) -> dict[str, str]:
    """Portees disponibles."""
    return dict(KNOWN_SCOPES)


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreateRequest, request: Request, identity: Identity, user: RecentUser
) -> ApiKeyCreatedResponse:
    """Cree une cle. Elle n'est affichee qu'ici, une seule fois."""
    try:
        issued = await identity.create_api_key(
            user, body.name, body.scopes, body.expires_in_days, client_ip(request)
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return ApiKeyCreatedResponse(
        id=issued.id,
        name=issued.name,
        prefix=issued.prefix,
        scopes=issued.scopes,
        expires_at=issued.expires_at,
        key=issued.secret,
    )


@router.get("/api-keys")
async def list_api_keys(identity: Identity, user: User) -> list[ApiKeyResponse]:
    """Cles de l'utilisateur, sans leur secret."""
    return [
        ApiKeyResponse(
            id=key.id,
            name=key.name,
            prefix=key.prefix,
            scopes=key.scopes,
            created_at=key.created_at,
            expires_at=key.expires_at,
            last_used_at=key.last_used_at,
            revoked_at=key.revoked_at,
        )
        for key in await identity.list_api_keys(user)
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID, request: Request, identity: Identity, user: RecentUser
) -> None:
    """Revoque une cle (definitif)."""
    if not await identity.revoke_api_key(user, key_id, client_ip(request)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cle introuvable ou deja revoquee.")


# ---------------------------------------------------------------------- audit
@router.get("/audit")
async def audit_events(identity: Identity, user: User) -> list[AuditEventResponse]:
    """50 derniers evenements de securite du compte."""
    return [
        AuditEventResponse(
            occurred_at=event.occurred_at,
            action=event.action,
            outcome=event.outcome,
            details=event.details,
        )
        for event in await identity.audit_events(user)
    ]
