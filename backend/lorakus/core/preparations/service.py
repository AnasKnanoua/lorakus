"""Preparations (ADR 0028) : un module prepare, le Core garde et montre.

    await prepare(session, user_id, "focus", "briefing", day, title, sections, now, expires_at)

- Une preparation par module, type et jour : la refaire la met a jour tant qu'elle n'a pas
  ete lue ; une fois lue (« consulted »), elle est figee et n'est plus montree.
- Montree tant qu'elle n'a pas expire ; seulement la plus recente de chaque module et
  type (le briefing de demain remplace celui d'aujourd'hui), trois au plus.
- Sections : des titres et des lignes de texte ecrits par le code du module (jamais par un
  modele), affiches tels quels (aucun Markdown).

Ces preparations sont calculees par des regles : leur cout est nul. Le budget de l'ADR 0028
(et la suspension d'une preparation ignoree trois fois) viendront avec la premiere
preparation qui coute (un appel a un modele) ou qui interrompt : le briefing ne sonne pas.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.planning.service import clean_line
from lorakus.core.preparations.models import PreparationRow

MAX_SHOWN: Final = 3  # ADR 0028
MAX_SECTIONS: Final = 8
MAX_LINES: Final = 10


class InvalidPreparationError(ValueError):
    """Preparation mal formee : une erreur de programmation du module."""


@dataclass(frozen=True)
class Section:
    heading: str
    lines: Sequence[str]


@dataclass(frozen=True)
class PreparationView:
    id: uuid.UUID
    module: str
    kind: str
    day: date
    title: str
    sections: list[Section]
    prepared_at: datetime


def _sections(sections: Sequence[Section]) -> list[dict[str, Any]]:
    if not 1 <= len(sections) <= MAX_SECTIONS:
        raise InvalidPreparationError(f"de 1 a {MAX_SECTIONS} sections")
    checked: list[dict[str, Any]] = []
    for section in sections:
        if not 1 <= len(section.lines) <= MAX_LINES:
            raise InvalidPreparationError(f"de 1 a {MAX_LINES} lignes par section")
        try:
            checked.append(
                {
                    "heading": clean_line(section.heading, 40),
                    "lines": [clean_line(line, 200, "ligne") for line in section.lines],
                }
            )
        except ValueError as error:
            raise InvalidPreparationError(str(error)) from None
    return checked


async def prepare(
    session: AsyncSession,
    user_id: uuid.UUID,
    module: str,
    kind: str,
    day: date,
    title: str,
    sections: Sequence[Section],
    now: datetime,
    expires_at: datetime,
) -> bool:
    """Cree ou met a jour la preparation de ce jour ; False si elle a deja ete lue (figee)."""
    if expires_at <= now:
        raise InvalidPreparationError("expiration passee")
    try:
        heading = clean_line(title, 120)
    except ValueError as error:
        raise InvalidPreparationError(str(error)) from None
    content = _sections(sections)
    saved = await session.scalar(
        insert(PreparationRow)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            module=module,
            kind=kind,
            day=day,
            title=heading,
            sections=content,
            status="ready",
            prepared_at=now,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            constraint="uq_core_preparations_user_id_module_kind_day",
            set_={
                "title": heading,
                "sections": content,
                "prepared_at": now,
                "expires_at": expires_at,
            },
            where=PreparationRow.status == "ready",
        )
        .returning(PreparationRow.id)
    )
    return saved is not None


async def list_ready(session: AsyncSession, now: datetime) -> list[PreparationView]:
    """Les preparations a montrer : pour chaque module et type, seulement la plus recente
    (le briefing de demain remplace celui d'aujourd'hui), trois au plus."""
    rows = list(
        await session.scalars(
            select(PreparationRow)
            .where(PreparationRow.status == "ready", PreparationRow.expires_at > now)
            .order_by(PreparationRow.day.desc(), PreparationRow.prepared_at.desc())
            .limit(50)
        )
    )
    latest: dict[tuple[str, str], PreparationRow] = {}
    for row in rows:
        latest.setdefault((row.module, row.kind), row)
    return [
        PreparationView(
            id=row.id,
            module=row.module,
            kind=row.kind,
            day=row.day,
            title=row.title,
            sections=[Section(s["heading"], list(s["lines"])) for s in row.sections],
            prepared_at=row.prepared_at,
        )
        for row in list(latest.values())[:MAX_SHOWN]
    ]


async def consult(session: AsyncSession, preparation_id: uuid.UUID, now: datetime) -> bool:
    """Lue : figee, plus montree. False si inconnue."""
    result = await session.execute(
        update(PreparationRow)
        .where(PreparationRow.id == preparation_id, PreparationRow.status == "ready")
        .values(status="consulted", consulted_at=now)
        .returning(PreparationRow.id)
    )
    if result.first() is not None:
        return True
    known = await session.scalar(
        select(PreparationRow.id).where(PreparationRow.id == preparation_id)
    )
    return known is not None
