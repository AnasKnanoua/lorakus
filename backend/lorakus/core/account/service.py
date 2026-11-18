"""Lecture et changement du fuseau de l'utilisateur.

Les fonctions recoivent une session deja liee a l'utilisateur (RLS) : elles s'executent dans
la transaction de l'appelant.
"""

import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import DEFAULT_TIMEZONE, parse_timezone
from lorakus.core.account.models import AccountSettings
from lorakus.core.identity.service import audit


async def timezone_name(session: AsyncSession) -> str:
    """Nom du fuseau de l'utilisateur de la session (par defaut Europe/Paris)."""
    value = await session.scalar(select(AccountSettings.timezone))
    return value or DEFAULT_TIMEZONE


async def user_timezone(session: AsyncSession) -> ZoneInfo:
    """Fuseau de l'utilisateur de la session ; un nom devenu inconnu redonne le defaut."""
    try:
        return parse_timezone(await timezone_name(session))
    except ValueError:
        return ZoneInfo(DEFAULT_TIMEZONE)


async def set_timezone(
    session: AsyncSession, user_id: uuid.UUID, name: str, ip: str | None = None
) -> str:
    """Change le fuseau (valide d'abord) ; le journal note le changement, sans le lieu."""
    parse_timezone(name)
    await session.execute(
        pg_insert(AccountSettings)
        .values(user_id=user_id, timezone=name)
        .on_conflict_do_update(
            index_elements=[AccountSettings.user_id],
            set_={"timezone": name, "updated_at": func.now()},
        )
    )
    await audit(session, user_id, "account.timezone_update", "success", ip, None)
    return name
