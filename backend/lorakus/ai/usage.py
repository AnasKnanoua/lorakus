"""Consommation IA par utilisateur : enregistrement et total du mois en cours.

La RLS limite chaque lecture a l'utilisateur de la transaction : le total du mois est
toujours celui de l'utilisateur courant, jamais celui d'un autre.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, insert, select

from lorakus.ai.models import AIUsage
from lorakus.ai.port import DataClass, Usage
from lorakus.db.database import Database


def month_start(now: datetime) -> datetime:
    """Debut du mois civil en UTC : le budget repart a zero le 1er a 00:00 UTC."""
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class UsageLedger(Protocol):
    """Ce dont le routeur a besoin : le total du mois et l'enregistrement d'un appel."""

    async def month_cost(self, user_id: uuid.UUID) -> Decimal: ...

    async def record(
        self,
        user_id: uuid.UUID,
        *,
        task: str,
        provider: str,
        model: str,
        data_class: DataClass,
        usage: Usage,
        cost_usd: Decimal,
        duration_ms: int,
    ) -> None: ...


class UsageStore:
    """Implementation PostgreSQL de UsageLedger (table core_ai_usage)."""

    def __init__(
        self, database: Database, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._db = database
        self._clock = clock

    async def month_cost(self, user_id: uuid.UUID) -> Decimal:
        """Depense de l'utilisateur depuis le debut du mois (UTC), en dollars."""
        async with self._db.transaction(user_id) as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(AIUsage.cost_usd), 0)).where(
                    AIUsage.user_id == user_id,
                    AIUsage.created_at >= month_start(self._clock()),
                )
            )
        return Decimal(total or 0)

    async def record(
        self,
        user_id: uuid.UUID,
        *,
        task: str,
        provider: str,
        model: str,
        data_class: DataClass,
        usage: Usage,
        cost_usd: Decimal,
        duration_ms: int,
    ) -> None:
        async with self._db.transaction(user_id) as session:
            await session.execute(
                insert(AIUsage).values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    task=task,
                    provider=provider,
                    model=model,
                    data_class=data_class,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                )
            )
