"""Type de colonne pgvector `halfvec` (vecteurs en demi-precision, ADR 0003).

Type ecrit ici plutot que la bibliotheque `pgvector` : quelques lignes suffisent (conversion
vers et depuis le texte « [x,y,z] »), sans dependance de plus. La demi-precision divise par
deux la place des vecteurs ; la perte est negligeable pour une similarite cosinus.
"""

from collections.abc import Sequence
from typing import Any, override

from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import UserDefinedType


class HalfVector(UserDefinedType[tuple[float, ...]]):
    """Colonne `lorakus.halfvec(n)` lue et ecrite comme un tuple de floats."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    @override
    def get_col_spec(self, **kw: Any) -> str:
        # Extension installee dans le schema lorakus (infra/postgres/init/01-roles.sh).
        return f"lorakus.halfvec({self.dimensions})"

    @override
    def bind_processor(self, dialect: Dialect):  # type deduit (fonction interne)
        dimensions = self.dimensions

        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            if len(value) != dimensions:
                raise ValueError(f"vecteur de {len(value)} dimensions au lieu de {dimensions}")
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    @override
    def result_processor(self, dialect: Dialect, coltype: object):  # type deduit
        def process(value: str | None) -> tuple[float, ...] | None:
            if value is None:
                return None
            return tuple(float(x) for x in value.strip("[]").split(","))

        return process
