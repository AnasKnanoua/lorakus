"""Reglages du compte (migration 0013). RLS forcee : chacun ne voit que les siens."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class AccountSettings(Base):
    """Reglages d'un utilisateur ; une ligne absente donne les valeurs par defaut."""

    __tablename__ = "core_account_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True
    )
    # Nom IANA (Europe/Paris, Europe/Istanbul...) : seul fuseau utilise pour dire
    # « aujourd'hui », placer un creneau ou donner l'heure au modele (ADR 0018).
    timezone: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
