"""Tables de l'identite. Protegees par la RLS : voir la migration 0002_core_identity."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Text,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class User(Base):
    """Un utilisateur. L'adresse e-mail est stockee en minuscules."""

    __tablename__ = "core_users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("role IN ('owner', 'admin', 'user')", name="role_known"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthSession(Base):
    """Une session de connexion. Seule l'empreinte SHA-256 du jeton est stockee."""

    __tablename__ = "core_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Derniere preuve d'identite (connexion ou re-authentification) : actions sensibles.
    reauthenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    """Tentative de connexion echouee, pour la limitation. Conservee 24 h au plus.

    Aucun acces direct pour l'application : seulement via les fonctions auth_*.
    """

    __tablename__ = "core_login_attempts"
    __table_args__ = (
        Index("ix_core_login_attempts_email_attempted_at", "email", "attempted_at"),
        Index("ix_core_login_attempts_ip_attempted_at", "ip", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _owner() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("core_users.id", ondelete="CASCADE"))


class Totp(Base):
    """Secret TOTP d'un utilisateur, chiffre. Actif une fois confirme par un premier code."""

    __tablename__ = "core_totp"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_encrypted: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Dernier pas de 30 s accepte : un code deja utilise ne passe plus (anti-rejeu).
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BackupCode(Base):
    """Code de secours : empreinte SHA-256, usage unique."""

    __tablename__ = "core_backup_codes"
    __table_args__ = (Index("ix_core_backup_codes_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = _owner()
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    """Cle d'API : prefixe visible, empreinte SHA-256, portees, expiration, revocation."""

    __tablename__ = "core_api_keys"
    __table_args__ = (Index("ix_core_api_keys_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = _owner()
    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text, unique=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    """Evenement d'audit. Ajout seul : ecrit par lorakus.audit_record(), jamais modifie."""

    __tablename__ = "core_audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'failure', 'denied')", name="outcome_known"),
        Index("ix_core_audit_events_user_id_occurred_at", "user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    action: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
