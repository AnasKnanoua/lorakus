"""Service d'identite : connexion, double authentification, sessions, cles d'API, audit.

Toutes les lectures de donnees d'un utilisateur passent par une transaction liee a cet
utilisateur (RLS). Avant authentification, seules les fonctions auth_* sont utilisees.
Chaque evenement de securite est inscrit au journal d'audit (ajout seul).
"""

import ipaddress
import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.identity import keys, totp
from lorakus.core.identity.crypto import FieldCipher, FieldEncryptionUnavailableError
from lorakus.core.identity.models import (
    ApiKey,
    AuditEvent,
    AuthSession,
    BackupCode,
    Totp,
    User,
)
from lorakus.core.identity.passwords import (
    MAX_PASSWORD_LENGTH,
    check_policy,
    dummy_hash,
    hash_password,
    verify_password,
)
from lorakus.core.identity.scopes import KNOWN_SCOPES
from lorakus.core.identity.tokens import looks_like_token, new_token, token_hash
from lorakus.db.database import Database, bind_user
from lorakus.settings import Settings

MAX_EMAIL_LENGTH: Final = 320
MAX_API_KEY_DAYS: Final = 365
# last_seen_at n'est reecrit qu'au plus une fois toutes les 5 minutes (moins d'ecritures).
LAST_SEEN_RESOLUTION: Final = timedelta(minutes=5)


class InvalidCredentialsError(Exception):
    """Identifiants refuses. Volontairement sans detail (compte inconnu, mot de passe faux)."""


class SecondFactorRequiredError(Exception):
    """Mot de passe correct, mais le compte exige un code de double authentification."""


class SecondFactorSetupRequiredError(Exception):
    """Double authentification obligatoire ici, mais pas encore activee sur ce compte."""


class SecondFactorMandatoryError(Exception):
    """Refus de desactiver la double authentification la ou elle est obligatoire."""


class TooManyAttemptsError(Exception):
    """Trop de tentatives echouees recentes pour ce compte ou cette adresse IP."""


class OwnerAlreadyExistsError(Exception):
    """Un proprietaire existe deja."""


class ConflictError(Exception):
    """Etat incompatible avec la demande (ex. double authentification deja active)."""


@dataclass(frozen=True)
class CurrentUser:
    """Utilisateur authentifie par session pour la requete en cours."""

    id: uuid.UUID
    email: str
    role: str
    session_id: uuid.UUID
    reauthenticated_at: datetime | None


@dataclass(frozen=True)
class ApiPrincipal:
    """Appelant authentifie par cle d'API."""

    user_id: uuid.UUID
    key_id: uuid.UUID
    scopes: frozenset[str]


@dataclass(frozen=True)
class IssuedSession:
    """Session creee : le jeton est a remettre au client, il n'est stocke nulle part."""

    token: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedApiKey:
    """Cle creee : `secret` n'est montre qu'une fois."""

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    expires_at: datetime
    secret: str


def normalize_email(email: str) -> str:
    """Adresse comparee sans espaces ni majuscules."""
    return email.strip().lower()[:MAX_EMAIL_LENGTH]


def parse_ip(value: str | None) -> str | None:
    """Adresse IP valide ou None (le client de test, par exemple, n'en a pas)."""
    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


async def audit(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    outcome: str,
    ip: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """Inscrit un evenement au journal (par la fonction, seul chemin d'ecriture permis)."""
    await session.execute(
        text(
            "SELECT lorakus.audit_record(:user_id, :action, :outcome, :ip, CAST(:details AS jsonb))"
        ),
        {
            "user_id": user_id,
            "action": action,
            "outcome": outcome,
            "ip": parse_ip(ip),
            "details": json.dumps(details or {}),
        },
    )


class IdentityService:
    """Regles d'identite. Une instance par application."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._db = database
        self._idle = timedelta(minutes=settings.session_idle_timeout_minutes)
        self._max_age = timedelta(hours=settings.session_max_age_hours)
        self._window = timedelta(minutes=settings.login_window_minutes)
        self._max_per_account = settings.login_max_failures_per_account
        self._max_per_ip = settings.login_max_failures_per_ip
        self.reauth_window = timedelta(minutes=settings.reauth_window_minutes)
        self._cipher = FieldCipher.from_settings(settings)
        # Obligatoire en production (Settings._production_rules) : sans second facteur
        # confirme, aucune session ne s'ouvre et les anciennes sessions sont refusees.
        self.second_factor_required = settings.require_second_factor

    # ------------------------------------------------------------------ connexion
    async def login(
        self, email: str, password: str, ip: str | None, second_factor: str | None = None
    ) -> IssuedSession:
        """Ouvre une session.

        Leve InvalidCredentialsError, TooManyAttemptsError ou SecondFactorRequiredError.
        Meme chemin, donc meme duree, que le compte existe ou non : un mot de passe est
        toujours verifie (celui du compte, ou un hachage factice).
        """
        email = normalize_email(email)
        ip = parse_ip(ip)
        async with self._db.transaction() as session:
            if await self._throttled(session, email, ip):
                await audit(session, None, "auth.login", "denied", ip, {"reason": "throttled"})
                locked = True
            else:
                locked = False
            account = (
                await session.execute(
                    text(
                        "SELECT id, password_hash, is_active FROM lorakus.auth_find_login(:email)"
                    ),
                    {"email": email},
                )
            ).one_or_none()
        if locked:
            raise TooManyAttemptsError

        stored_hash = account.password_hash if account is not None else dummy_hash()
        result = await verify_password(stored_hash, password[:MAX_PASSWORD_LENGTH])
        password_ok = account is not None and account.is_active and result.ok
        new_hash = await hash_password(password) if password_ok and result.needs_rehash else None

        issued: IssuedSession | None = None
        error: Exception | None = None
        async with self._db.transaction() as session:
            user_id = account.id if account is not None and password_ok else None
            if user_id is None:
                error = InvalidCredentialsError()
                reason = "credentials"
            else:
                await bind_user(session, user_id)
                method = await self._second_factor(session, user_id, second_factor, ip)
                if method == "missing":
                    error, reason = SecondFactorRequiredError(), "second_factor_required"
                elif method == "invalid":
                    error, reason = InvalidCredentialsError(), "second_factor"
                elif method == "none" and self.second_factor_required:
                    error, reason = SecondFactorSetupRequiredError(), "second_factor_setup"
                else:
                    reason = method
                    if new_hash is not None:
                        await session.execute(
                            update(User).where(User.id == user_id).values(password_hash=new_hash)
                        )
                    issued = await self._create_session(session, user_id)
            failed = isinstance(error, InvalidCredentialsError)
            if not isinstance(error, (SecondFactorRequiredError, SecondFactorSetupRequiredError)):
                await session.execute(
                    text("SELECT lorakus.auth_record_attempt(:email, :ip, :ok)"),
                    {"email": email, "ip": ip, "ok": not failed},
                )
            outcome = "success" if issued is not None else "failure"
            # Un echec sur un compte existant est inscrit a son nom : le titulaire voit qu'on a
            # essaye son mot de passe. Le journal n'est lisible que par lui.
            target = account.id if account is not None else None
            await audit(session, target, "auth.login", outcome, ip, {"method": reason})
        # Leve APRES la transaction : l'echec et l'audit enregistres ci-dessus sont conserves.
        if error is not None:
            raise error
        if issued is None:
            raise InvalidCredentialsError
        return issued

    async def authenticate(self, token: str) -> CurrentUser | None:
        """Utilisateur de la session, ou None si le jeton est inconnu, expire ou inactif."""
        if not looks_like_token(token):
            return None
        now = datetime.now(UTC)
        async with self._db.transaction() as session:
            found = (
                await session.execute(
                    text(
                        "SELECT id, user_id, last_seen_at, expires_at "
                        "FROM lorakus.auth_find_session(:hash)"
                    ),
                    {"hash": token_hash(token)},
                )
            ).one_or_none()
            if found is None:
                return None
            await bind_user(session, found.user_id)
            if now >= found.expires_at or now - found.last_seen_at >= self._idle:
                await session.execute(delete(AuthSession).where(AuthSession.id == found.id))
                return None
            row = (
                await session.execute(
                    select(
                        User.id,
                        User.email,
                        User.role,
                        User.is_active,
                        AuthSession.reauthenticated_at,
                        Totp.confirmed_at.label("second_factor_since"),
                    )
                    .join(AuthSession, AuthSession.user_id == User.id)
                    .outerjoin(Totp, (Totp.user_id == User.id) & Totp.confirmed_at.is_not(None))
                    .where(AuthSession.id == found.id)
                )
            ).one_or_none()
            if row is None or not row.is_active:
                return None
            if self.second_factor_required and row.second_factor_since is None:
                # Session ouverte avant que la double authentification ne soit exigee
                # (ou apres une recuperation sur le serveur) : elle n'est plus valable.
                await session.execute(delete(AuthSession).where(AuthSession.id == found.id))
                return None
            if now - found.last_seen_at >= LAST_SEEN_RESOLUTION:
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.id == found.id)
                    .values(last_seen_at=func.now())
                )
            return CurrentUser(
                id=row.id,
                email=row.email,
                role=row.role,
                session_id=found.id,
                reauthenticated_at=row.reauthenticated_at,
            )

    def recently_authenticated(self, user: CurrentUser) -> bool:
        """Vrai si la derniere preuve d'identite date de moins de reauth_window."""
        return (
            user.reauthenticated_at is not None
            and datetime.now(UTC) - user.reauthenticated_at < self.reauth_window
        )

    async def reauthenticate(
        self, user: CurrentUser, password: str, second_factor: str | None, ip: str | None
    ) -> None:
        """Nouvelle preuve d'identite (mot de passe, et code si active) pour la session."""
        ip = parse_ip(ip)
        async with self._db.transaction(user.id) as session:
            if await self._throttled(session, user.email, ip):
                await audit(session, user.id, "auth.reauth", "denied", ip, {"reason": "throttled"})
                throttled = True
            else:
                throttled = False
            stored_hash = await session.scalar(select(User.password_hash).where(User.id == user.id))
        if throttled:
            raise TooManyAttemptsError
        result = await verify_password(stored_hash or dummy_hash(), password[:MAX_PASSWORD_LENGTH])
        error: Exception | None = None
        async with self._db.transaction(user.id) as session:
            if stored_hash is None or not result.ok:
                error = InvalidCredentialsError()
            else:
                method = await self._second_factor(session, user.id, second_factor, ip)
                if method == "missing":
                    error = SecondFactorRequiredError()
                elif method == "invalid":
                    error = InvalidCredentialsError()
                else:
                    await session.execute(
                        update(AuthSession)
                        .where(AuthSession.id == user.session_id)
                        .values(reauthenticated_at=func.now())
                    )
            if isinstance(error, InvalidCredentialsError):
                await session.execute(
                    text("SELECT lorakus.auth_record_attempt(:email, :ip, false)"),
                    {"email": user.email, "ip": ip},
                )
            outcome = "success" if error is None else "failure"
            await audit(session, user.id, "auth.reauth", outcome, ip)
        if error is not None:
            raise error

    async def logout(self, user: CurrentUser, ip: str | None = None) -> None:
        """Supprime la session courante."""
        async with self._db.transaction(user.id) as session:
            await session.execute(delete(AuthSession).where(AuthSession.id == user.session_id))
            await audit(session, user.id, "auth.logout", "success", ip)

    async def change_password(
        self, user: CurrentUser, current_password: str, new_password: str, ip: str | None
    ) -> IssuedSession:
        """Change le mot de passe, revoque TOUTES les sessions, en ouvre une nouvelle."""
        check_policy(new_password)
        async with self._db.transaction(user.id) as session:
            stored_hash = await session.scalar(select(User.password_hash).where(User.id == user.id))
        result = await verify_password(stored_hash or dummy_hash(), current_password)
        if stored_hash is None or not result.ok:
            # Compte comme un echec de connexion : pas de force brute par cette route.
            async with self._db.transaction(user.id) as session:
                await session.execute(
                    text("SELECT lorakus.auth_record_attempt(:email, :ip, false)"),
                    {"email": user.email, "ip": parse_ip(ip)},
                )
                await audit(session, user.id, "auth.password_change", "failure", ip)
            raise InvalidCredentialsError
        new_hash = await hash_password(new_password)
        async with self._db.transaction(user.id) as session:
            await session.execute(
                update(User)
                .where(User.id == user.id)
                .values(password_hash=new_hash, password_changed_at=func.now())
            )
            await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            await audit(session, user.id, "auth.password_change", "success", ip)
            return await self._create_session(session, user.id)

    # ------------------------------------------------------------------ double authentification
    async def totp_setup(self, user: CurrentUser) -> tuple[str, str]:
        """Prepare un secret (pas encore actif) : (secret, adresse otpauth://)."""
        cipher = self._require_cipher()
        secret = totp.new_secret()
        async with self._db.transaction(user.id) as session:
            existing = await session.scalar(
                select(Totp.confirmed_at).where(Totp.user_id == user.id)
            )
            if existing is not None:
                raise ConflictError("La double authentification est deja active.")
            await session.execute(delete(Totp).where(Totp.user_id == user.id))
            await session.execute(
                insert(Totp).values(
                    user_id=user.id,
                    secret_encrypted=cipher.encrypt(secret.encode("ascii"), user.id.bytes),
                )
            )
        return secret, totp.provisioning_uri(secret, user.email)

    async def totp_confirm(self, user: CurrentUser, code: str, ip: str | None) -> list[str]:
        """Active la double authentification avec un premier code ; renvoie les codes de secours."""
        cipher = self._require_cipher()
        async with self._db.transaction(user.id) as session:
            row = (
                await session.execute(select(Totp).where(Totp.user_id == user.id))
            ).scalar_one_or_none()
            if row is None or row.confirmed_at is not None:
                raise ConflictError("Aucune configuration en attente.")
            secret = cipher.decrypt(row.secret_encrypted, user.id.bytes).decode("ascii")
            step = totp.matching_step(secret, code, time.time(), None)
            if step is None:
                raise InvalidCredentialsError
            await session.execute(
                update(Totp)
                .where(Totp.user_id == user.id)
                .values(confirmed_at=func.now(), last_used_step=step)
            )
            codes = await self._replace_backup_codes(session, user.id)
            await audit(session, user.id, "auth.totp_enable", "success", ip)
        return codes

    async def totp_disable(self, user: CurrentUser, ip: str | None) -> None:
        """Desactive la double authentification (re-authentification recente exigee par l'API).

        Refuse la ou elle est obligatoire : le seul recours est alors recover-second-factor
        sur le serveur, suivi d'une nouvelle activation (enable-second-factor).
        """
        if self.second_factor_required:
            raise SecondFactorMandatoryError
        async with self._db.transaction(user.id) as session:
            await session.execute(delete(Totp).where(Totp.user_id == user.id))
            await session.execute(delete(BackupCode).where(BackupCode.user_id == user.id))
            await audit(session, user.id, "auth.totp_disable", "success", ip)

    async def regenerate_backup_codes(self, user: CurrentUser, ip: str | None) -> list[str]:
        """Remplace tous les codes de secours."""
        async with self._db.transaction(user.id) as session:
            confirmed = await session.scalar(
                select(Totp.confirmed_at).where(Totp.user_id == user.id)
            )
            if confirmed is None:
                raise ConflictError("La double authentification n'est pas active.")
            codes = await self._replace_backup_codes(session, user.id)
            await audit(session, user.id, "auth.backup_codes_regenerate", "success", ip)
        return codes

    async def totp_enabled(self, user: CurrentUser) -> bool:
        async with self._db.transaction(user.id) as session:
            confirmed = await session.scalar(
                select(Totp.confirmed_at).where(Totp.user_id == user.id)
            )
        return confirmed is not None

    # ------------------------------------------------------------------ cles d'API
    async def create_api_key(
        self, user: CurrentUser, name: str, scopes: Sequence[str], days: int, ip: str | None
    ) -> IssuedApiKey:
        """Cree une cle. Le secret n'est renvoye qu'ici, une seule fois."""
        unknown = sorted(set(scopes) - KNOWN_SCOPES.keys())
        if unknown or not scopes:
            raise ValueError(f"Portees inconnues ou vides : {', '.join(unknown) or 'aucune'}")
        if not 1 <= days <= MAX_API_KEY_DAYS:
            raise ValueError(f"Duree de validite : 1 a {MAX_API_KEY_DAYS} jours.")
        prefix, secret = keys.new_api_key()
        key_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + timedelta(days=days)
        scope_list = sorted(set(scopes))
        async with self._db.transaction(user.id) as session:
            await session.execute(
                insert(ApiKey).values(
                    id=key_id,
                    user_id=user.id,
                    name=name,
                    prefix=prefix,
                    key_hash=keys.digest(secret),
                    scopes=scope_list,
                    expires_at=expires_at,
                )
            )
            await audit(
                session,
                user.id,
                "auth.api_key_create",
                "success",
                ip,
                {"prefix": prefix, "scopes": scope_list},
            )
        return IssuedApiKey(key_id, name, prefix, scope_list, expires_at, secret)

    async def list_api_keys(self, user: CurrentUser) -> list[ApiKey]:
        async with self._db.transaction(user.id) as session:
            return list(
                (await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars()
            )

    async def revoke_api_key(self, user: CurrentUser, key_id: uuid.UUID, ip: str | None) -> bool:
        async with self._db.transaction(user.id) as session:
            prefix = await session.scalar(
                update(ApiKey)
                .where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
                .values(revoked_at=func.now())
                .returning(ApiKey.prefix)
            )
            if prefix is not None:
                await audit(
                    session, user.id, "auth.api_key_revoke", "success", ip, {"prefix": prefix}
                )
        return prefix is not None

    async def authenticate_api_key(self, raw: str, ip: str | None) -> ApiPrincipal | None:
        """Appelant de la cle, ou None (inconnue, fausse, expiree ou revoquee)."""
        prefix = keys.split_api_key(raw)
        if prefix is None:
            return None
        async with self._db.transaction() as session:
            found = (
                await session.execute(
                    text(
                        "SELECT id, user_id, key_hash, scopes, expires_at, revoked_at "
                        "FROM lorakus.auth_find_api_key(:prefix)"
                    ),
                    {"prefix": prefix},
                )
            ).one_or_none()
            if found is None or not keys.constant_time_equal(found.key_hash, keys.digest(raw)):
                return None
            await bind_user(session, found.user_id)
            if found.revoked_at is not None or datetime.now(UTC) >= found.expires_at:
                await audit(
                    session,
                    found.user_id,
                    "auth.api_key_use",
                    "denied",
                    ip,
                    {"prefix": prefix, "reason": "revoked" if found.revoked_at else "expired"},
                )
                return None
            await session.execute(
                update(ApiKey)
                .where(
                    ApiKey.id == found.id,
                    (ApiKey.last_used_at.is_(None))
                    | (ApiKey.last_used_at < func.now() - LAST_SEEN_RESOLUTION),
                )
                .values(last_used_at=func.now())
            )
        return ApiPrincipal(found.user_id, found.id, frozenset(found.scopes))

    # ------------------------------------------------------------------ audit
    async def audit_events(self, user: CurrentUser, limit: int = 50) -> list[AuditEvent]:
        async with self._db.transaction(user.id) as session:
            return list(
                (
                    await session.execute(
                        select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
                    )
                ).scalars()
            )

    # ------------------------------------------------------------------ proprietaire
    async def create_owner(self, email: str, password: str) -> uuid.UUID:
        """Cree le compte proprietaire (commande sur le serveur). Un seul proprietaire."""
        check_policy(password)
        email = normalize_email(email)
        if "@" not in email:
            raise ValueError("Adresse e-mail invalide.")
        password_hash = await hash_password(password)
        user_id = uuid.uuid4()
        async with self._db.transaction() as session:
            if await session.scalar(text("SELECT lorakus.auth_owner_exists()")):
                raise OwnerAlreadyExistsError
            await bind_user(session, user_id)
            await session.execute(
                insert(User).values(
                    id=user_id, email=email, password_hash=password_hash, role="owner"
                )
            )
            await audit(session, user_id, "auth.owner_create", "success")
        return user_id

    async def account_for_admin(self, email: str) -> CurrentUser | None:
        """Compte designe par son adresse, pour une commande sur le serveur (sans session)."""
        async with self._db.transaction() as session:
            account = (
                await session.execute(
                    text("SELECT id, is_active FROM lorakus.auth_find_login(:email)"),
                    {"email": normalize_email(email)},
                )
            ).one_or_none()
            if account is None or not account.is_active:
                return None
            await bind_user(session, account.id)
            row = (
                await session.execute(select(User.email, User.role).where(User.id == account.id))
            ).one()
        return CurrentUser(
            id=account.id,
            email=row.email,
            role=row.role,
            session_id=uuid.UUID(int=0),
            reauthenticated_at=None,
        )

    async def recover_second_factor(self, email: str) -> bool:
        """Desactive la double authentification d'un compte (commande sur le serveur).

        Recours si le telephone ET les codes de secours sont perdus. Reserve a qui a deja
        un acces administrateur au serveur ; toutes les sessions du compte sont revoquees.
        """
        async with self._db.transaction() as session:
            account = (
                await session.execute(
                    text("SELECT id FROM lorakus.auth_find_login(:email)"),
                    {"email": normalize_email(email)},
                )
            ).one_or_none()
            if account is None:
                return False
            await bind_user(session, account.id)
            await session.execute(delete(Totp).where(Totp.user_id == account.id))
            await session.execute(delete(BackupCode).where(BackupCode.user_id == account.id))
            await session.execute(delete(AuthSession).where(AuthSession.user_id == account.id))
            await audit(session, account.id, "auth.totp_recovery", "success", None, {"via": "cli"})
        return True

    # ------------------------------------------------------------------ interne
    def _require_cipher(self) -> FieldCipher:
        if self._cipher is None:
            raise FieldEncryptionUnavailableError
        return self._cipher

    async def _throttled(self, session: AsyncSession, email: str, ip: str | None) -> bool:
        failures = (
            await session.execute(
                text("SELECT by_email, by_ip FROM lorakus.auth_failures(:email, :ip, :since)"),
                {"email": email, "ip": ip, "since": datetime.now(UTC) - self._window},
            )
        ).one()
        return failures.by_email >= self._max_per_account or failures.by_ip >= self._max_per_ip

    async def _second_factor(
        self, session: AsyncSession, user_id: uuid.UUID, code: str | None, ip: str | None
    ) -> str:
        """Verifie le second facteur si le compte en a un (session liee a l'utilisateur).

        Renvoie "none" (pas de double authentification), "totp", "backup_code",
        "missing" (code exige mais absent) ou "invalid".
        """
        row = (
            await session.execute(
                select(Totp).where(Totp.user_id == user_id, Totp.confirmed_at.is_not(None))
            )
        ).scalar_one_or_none()
        if row is None:
            return "none"
        if not code:
            return "missing"
        if self._cipher is not None:
            secret = self._cipher.decrypt(row.secret_encrypted, user_id.bytes).decode("ascii")
            step = totp.matching_step(secret, code, time.time(), row.last_used_step)
            if step is not None:
                # Conditionnel : deux requetes simultanees avec le meme code -> une seule passe.
                updated = await session.execute(
                    update(Totp)
                    .where(
                        Totp.user_id == user_id,
                        (Totp.last_used_step.is_(None)) | (Totp.last_used_step < step),
                    )
                    .values(last_used_step=step)
                    .returning(Totp.user_id)
                )
                return "totp" if updated.first() is not None else "invalid"
        used = await session.scalar(
            update(BackupCode)
            .where(
                BackupCode.user_id == user_id,
                BackupCode.code_hash == keys.digest(keys.normalize_backup_code(code)),
                BackupCode.used_at.is_(None),
            )
            .values(used_at=func.now())
            .returning(BackupCode.id)
        )
        if used is not None:
            await audit(session, user_id, "auth.backup_code_used", "success", ip)
            return "backup_code"
        return "invalid"

    async def _replace_backup_codes(self, session: AsyncSession, user_id: uuid.UUID) -> list[str]:
        codes = keys.new_backup_codes()
        await session.execute(delete(BackupCode).where(BackupCode.user_id == user_id))
        await session.execute(
            insert(BackupCode),
            [
                {
                    "id": uuid.uuid4(),
                    "user_id": user_id,
                    "code_hash": keys.digest(keys.normalize_backup_code(code)),
                }
                for code in codes
            ],
        )
        return codes

    async def _create_session(self, session: AsyncSession, user_id: uuid.UUID) -> IssuedSession:
        token = new_token()
        now = datetime.now(UTC)
        expires_at = now + self._max_age
        await session.execute(
            insert(AuthSession).values(
                id=uuid.uuid4(),
                user_id=user_id,
                token_hash=token_hash(token),
                last_seen_at=now,
                expires_at=expires_at,
                # Une connexion complete est une preuve d'identite fraiche.
                reauthenticated_at=now,
            )
        )
        return IssuedSession(token=token, expires_at=expires_at)
