"""Limites de debit par utilisateur, en fenetres fixes, stockees dans PostgreSQL.

Pourquoi PostgreSQL et pas la memoire du processus : les compteurs survivent a un
redemarrage et restent justes si l'API tourne un jour dans plusieurs processus. Une requete
ajoute une ecriture courte (une ligne par compteur, mise a jour sur place).

Fenetres fixes : un utilisateur peut au pire faire le double de la limite a cheval sur deux
fenetres. C'est accepte : il s'agit de borner un abus ou une boucle, pas de facturer.
Une requete refusee est comptee aussi : un client qui insiste reste bloque.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from lorakus.core.ratelimit.models import RateLimitCounter
from lorakus.db.database import Database
from lorakus.observability.metrics import RATE_LIMITED


@dataclass(frozen=True)
class Limit:
    """Au plus `max_hits` passages dans une fenetre de `window_seconds` secondes."""

    bucket: str
    window_seconds: int
    max_hits: int

    def __post_init__(self) -> None:
        if self.window_seconds < 1 or self.max_hits < 1:
            raise ValueError("fenetre et maximum doivent etre strictement positifs")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0  # secondes avant de pouvoir reessayer (0 si autorise)
    bucket: str | None = None  # compteur depasse


class RateLimiter:
    """Compte un passage dans chaque limite et dit s'il est autorise."""

    def __init__(
        self, database: Database, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._db = database
        self._clock = clock

    async def hit(self, user_id: uuid.UUID, limits: Sequence[Limit]) -> Decision:
        """Ajoute un passage a chaque compteur ; refuse si l'un d'eux depasse son maximum."""
        now = int(self._clock().timestamp())
        refused: Decision | None = None
        # Toujours le meme ordre de verrouillage des lignes : pas d'interblocage.
        ordered = sorted(limits, key=lambda limit: limit.bucket)
        async with self._db.transaction(user_id) as session:
            for limit in ordered:
                start = now - now % limit.window_seconds
                window_start = datetime.fromtimestamp(start, UTC)
                statement = insert(RateLimitCounter).values(
                    user_id=user_id, bucket=limit.bucket, window_start=window_start, hits=1
                )
                hits = await session.scalar(
                    statement.on_conflict_do_update(
                        index_elements=[
                            RateLimitCounter.user_id,
                            RateLimitCounter.bucket,
                            RateLimitCounter.window_start,
                        ],
                        set_={"hits": RateLimitCounter.hits + 1},
                    ).returning(RateLimitCounter.hits)
                )
                if hits == 1:
                    # Nouvelle fenetre : les precedentes de ce compteur ne servent plus.
                    await session.execute(
                        delete(RateLimitCounter).where(
                            RateLimitCounter.user_id == user_id,
                            RateLimitCounter.bucket == limit.bucket,
                            RateLimitCounter.window_start < window_start,
                        )
                    )
                if (hits or 0) > limit.max_hits:
                    retry_after = max(1, start + limit.window_seconds - now)
                    if refused is None or retry_after > refused.retry_after:
                        refused = Decision(False, retry_after, limit.bucket)
        if refused is not None:
            RATE_LIMITED.labels(bucket=refused.bucket or "").inc()
            return refused
        return Decision(True)


class AICallQuota:
    """Rythme des appels IA d'un utilisateur, pour le ModelRouter (port CallQuota)."""

    def __init__(self, limiter: RateLimiter, *, per_minute: int, per_day: int) -> None:
        self._limiter = limiter
        self._limits = (
            Limit("ai.minute", 60, per_minute),
            Limit("ai.day", 86_400, per_day),
        )

    async def allow(self, user_id: uuid.UUID) -> bool:
        return (await self._limiter.hit(user_id, self._limits)).allowed
