"""Service d'identite : connexion, sessions, changement de mot de passe, proprietaire.

Toutes les lectures de donnees d'un utilisateur passent par une transaction liee a cet
utilisateur (RLS). Avant authentification, seules les fonctions auth_* sont utilisees.
"""

import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.identity.models import AuthSession, User
from lorakus.core.identity.passwords import (
    MAX_PASSWORD_LENGTH,
    check_policy,
    dummy_hash,
    hash_password,
    verify_password,
)
from lorakus.core.identity.tokens import looks_like_token, new_token, token_hash
from lorakus.db.database import Database, bind_user
from lorakus.settings import Settings

MAX_EMAIL_LENGTH: Final = 320
# last_seen_at n'est reecrit qu'au plus une fois toutes les 5 minutes (moins d'ecritures).
LAST_SEEN_RESOLUTION: Final = timedelta(minutes=5)


class InvalidCredentialsError(Exception):
    """Identifiants refuses. Volontairement sans detail (compte inconnu ou mot de passe faux)."""


class TooManyAttemptsError(Exception):
    """Trop de tentatives echouees recentes pour ce compte ou cette adresse IP."""


class OwnerAlreadyExistsError(Exception):
    """Un proprietaire existe deja."""


@dataclass(frozen=True)
class CurrentUser:
    """Utilisateur authentifie de la requete en cours."""

    id: uuid.UUID
    email: str
    role: str


@dataclass(frozen=True)
class IssuedSession:
    """Session creee : le jeton est a remettre au client, il n'est stocke nulle part."""

    token: str
    expires_at: datetime


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


class IdentityService:
    """Regles d'identite. Une instance par application."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self._db = database
        self._idle = timedelta(minutes=settings.session_idle_timeout_minutes)
        self._max_age = timedelta(hours=settings.session_max_age_hours)
        self._window = timedelta(minutes=settings.login_window_minutes)
        self._max_per_account = settings.login_max_failures_per_account
        self._max_per_ip = settings.login_max_failures_per_ip

    # ------------------------------------------------------------------ connexion
    async def login(self, email: str, password: str, ip: str | None) -> IssuedSession:
        """Ouvre une session, ou leve InvalidCredentialsError / TooManyAttemptsError.

        Meme chemin, donc meme duree, que le compte existe ou non : un mot de passe est
        toujours verifie (celui du compte, ou un hachage factice).
        """
        email = normalize_email(email)
        ip = parse_ip(ip)
        since = datetime.now(UTC) - self._window

        async with self._db.transaction() as session:
            failures = (
                await session.execute(
                    text("SELECT by_email, by_ip FROM lorakus.auth_failures(:email, :ip, :since)"),
                    {"email": email, "ip": ip, "since": since},
                )
            ).one()
            if failures.by_email >= self._max_per_account or failures.by_ip >= self._max_per_ip:
                raise TooManyAttemptsError
            account = (
                await session.execute(
                    text(
                        "SELECT id, password_hash, is_active FROM lorakus.auth_find_login(:email)"
                    ),
                    {"email": email},
                )
            ).one_or_none()

        stored_hash = account.password_hash if account is not None else dummy_hash()
        result = await verify_password(stored_hash, password[:MAX_PASSWORD_LENGTH])
        succeeded = account is not None and account.is_active and result.ok
        new_hash = await hash_password(password) if succeeded and result.needs_rehash else None

        async with self._db.transaction() as session:
            await session.execute(
                text("SELECT lorakus.auth_record_attempt(:email, :ip, :ok)"),
                {"email": email, "ip": ip, "ok": succeeded},
            )
            issued: IssuedSession | None = None
            if succeeded and account is not None:
                await bind_user(session, account.id)
                if new_hash is not None:
                    await session.execute(
                        update(User).where(User.id == account.id).values(password_hash=new_hash)
                    )
                issued = await self._create_session(session, account.id)
        # Leve APRES la fin de la transaction : l'echec enregistre ci-dessus est conserve.
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
            user = (
                await session.execute(
                    select(User.id, User.email, User.role, User.is_active).where(
                        User.id == found.user_id
                    )
                )
            ).one_or_none()
            if user is None or not user.is_active:
                return None
            if now - found.last_seen_at >= LAST_SEEN_RESOLUTION:
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.id == found.id)
                    .values(last_seen_at=func.now())
                )
            return CurrentUser(id=user.id, email=user.email, role=user.role)

    async def logout(self, user: CurrentUser, token: str) -> None:
        """Supprime la session courante."""
        async with self._db.transaction(user.id) as session:
            await session.execute(
                delete(AuthSession).where(AuthSession.token_hash == token_hash(token))
            )

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
            async with self._db.transaction() as session:
                await session.execute(
                    text("SELECT lorakus.auth_record_attempt(:email, :ip, false)"),
                    {"email": user.email, "ip": parse_ip(ip)},
                )
            raise InvalidCredentialsError
        new_hash = await hash_password(new_password)
        async with self._db.transaction(user.id) as session:
            await session.execute(
                update(User)
                .where(User.id == user.id)
                .values(password_hash=new_hash, password_changed_at=func.now())
            )
            await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            return await self._create_session(session, user.id)

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
        return user_id

    # ------------------------------------------------------------------ interne
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
            )
        )
        return IssuedSession(token=token, expires_at=expires_at)
