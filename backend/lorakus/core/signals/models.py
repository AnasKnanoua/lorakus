"""Tables des signaux et des notifications (migration 0017, ADR 0042). RLS forcee.

- `core_signals` : une cause d'interruption proposee par un module (« devoir a rendre dans
  3 jours, pas commence »), son texte ecrit par le code, ses faits (pour « Pourquoi ? ») et
  l'etat de sa carte dans l'application (vue, fermee, repoussee). Une cause n'existe qu'une
  fois par utilisateur : `dedup_key` est unique.
- `core_interventions` : chaque fois que la politique a decide d'interrompre pour un signal,
  a quel niveau, par quel canal, et pourquoi. Un niveau au plus par signal (unique) : c'est
  ce qui garantit l'absence de doublon, meme si deux processus decidaient en meme temps.
- `core_push_subscriptions` : les appareils abonnes aux notifications (Web Push).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class SignalRow(Base):
    __tablename__ = "core_signals"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_core_signals_id_user_id"),
        UniqueConstraint("user_id", "dedup_key", name="uq_core_signals_user_id_dedup_key"),
        Index(
            "ix_core_signals_next_check_at",
            "next_check_at",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_core_signals_user_id_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    module: Mapped[str] = mapped_column(Text)  # proprietaire : « focus », ou « core »
    name: Mapped[str] = mapped_column(Text)  # « focus.deadline_soon »
    kind: Mapped[str] = mapped_column(Text)  # scheduled | contextual | proactive
    strength: Mapped[float] = mapped_column(Float)
    data_class: Mapped[str] = mapped_column(Text)  # public | personal | sensitive
    subject_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # « task:<uuid> »
    dedup_key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    firm_body: Mapped[str | None] = mapped_column(Text, nullable=True)  # texte du niveau 2
    rule: Mapped[str] = mapped_column(Text)  # la regle, en clair (« Pourquoi ? »)
    facts: Mapped[Any] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    url: Mapped[str] = mapped_column(Text)  # page de l'application a ouvrir
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Etat de la carte dans l'application.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InterventionRow(Base):
    __tablename__ = "core_interventions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["signal_id", "user_id"],
            ["core_signals.id", "core_signals.user_id"],
            name="fk_core_interventions_signal_id_core_signals",
            ondelete="CASCADE",
        ),
        UniqueConstraint("signal_id", "level", name="uq_core_interventions_signal_id_level"),
        Index("ix_core_interventions_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    level: Mapped[int] = mapped_column(SmallInteger)  # 1 : application ; 2 : notification
    channel: Mapped[str] = mapped_column(Text)  # app | push
    reason: Mapped[str] = mapped_column(Text)
    decision: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Notification acceptee par au moins un service (canal push), ou echec.
    delivered: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    failed: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PushSubscriptionRow(Base):
    __tablename__ = "core_push_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", name="uq_core_push_subscriptions_user_id_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    # Adresse donnee par le navigateur : jamais renvoyee par l'API, ni exportee, ni journalisee.
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)  # « Chrome sur Android »
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
