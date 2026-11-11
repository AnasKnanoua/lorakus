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
    true,
)
from sqlalchemy.dialects.postgresql import INET
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
