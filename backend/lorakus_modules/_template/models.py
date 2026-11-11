"""Tables du module Template. Toutes prefixees, toutes avec user_id et RLS (voir migrations/)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from lorakus.db.base import Base


class TemplateItem(Base):
    """Exemple de table : un element appartenant a un utilisateur."""

    __tablename__ = "tpl_items"
    __table_args__ = (Index("ix_tpl_items_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core_users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
