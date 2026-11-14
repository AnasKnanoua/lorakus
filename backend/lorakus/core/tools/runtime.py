"""Execution des outils : validation, confirmation, audit (ADR 0012, PR 38).

Toute action passe par ici, qu'elle vienne de l'API ou d'un modele dans le chat :

- read : executee tout de suite ;
- write et sensitive : mises en attente d'une confirmation a usage unique, valable
  10 minutes, aux arguments figes. La carte affiche le texte calcule par l'outil (summary).
  La confirmation n'arrive que par l'API, avec la session de l'utilisateur ; une action
  sensitive exige en plus une preuve d'identite recente (verifiee par la route).

Confirmer reserve la ligne, execute l'outil et l'audite dans UNE transaction : si l'outil
echoue, rien n'est consomme (la carte reste en attente) ; deux clics simultanes n'executent
qu'une fois (le second attend le verrou, puis ne trouve plus de ligne libre).
Apres decision, les arguments sont effaces : la ligne ne garde que l'outil et l'issue.
"""

import json
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from opentelemetry import trace
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from lorakus.core.identity.service import audit
from lorakus.core.modules.service import ModuleService
from lorakus.core.tools.models import ToolConfirmation
from lorakus.core.tools.spec import (
    MAX_RESULT_CHARS,
    MAX_SUMMARY_CHARS,
    ToolCall,
    ToolError,
    ToolPorts,
    ToolSpec,
)
from lorakus.db.database import Database

__all__ = ["CONFIRMATION_TTL", "ConfirmationStatus", "ToolError", "ToolResult", "ToolRuntime"]

CONFIRMATION_TTL: Final = timedelta(minutes=10)
_TRACER = trace.get_tracer("lorakus.tools")

ConfirmationStatus = Literal["pending", "confirmed", "cancelled", "expired"]


@dataclass(frozen=True)
class ToolResult:
    """Resultat d'un appel : execute (result) ou en attente de confirmation (confirmation_id)."""

    tool: str
    result: dict[str, Any] | None = None
    confirmation_id: uuid.UUID | None = None
    risk: str = "read"
    summary: str | None = None
    expires_at: datetime | None = None


def _clean_summary(text: str) -> str:
    """Texte de carte : sans caractere de controle (sauf saut de ligne), borne en longueur."""
    kept = "".join(c for c in text if c == "\n" or unicodedata.category(c) != "Cc").strip()
    if not kept:
        raise ToolError("action impossible a decrire")
    return kept if len(kept) <= MAX_SUMMARY_CHARS else kept[: MAX_SUMMARY_CHARS - 1] + "…"


class ToolRuntime:
    """Point de passage unique de toute action, qu'elle vienne de l'API ou d'un LLM."""

    def __init__(
        self, database: Database, modules: ModuleService, ports: ToolPorts | None = None
    ) -> None:
        self._db = database
        self._modules = modules
        self._ports = ports or ToolPorts()
        self._tools: dict[str, tuple[str, ToolSpec]] = {
            tool.name: (manifest.id, tool)
            for manifest in modules.registry
            for tool in manifest.tools
        }

    def spec(self, name: str) -> ToolSpec | None:
        found = self._tools.get(name)
        return found[1] if found else None

    async def available(self, user_id: uuid.UUID) -> list[ToolSpec]:
        enabled = {s.manifest.id for s in await self._modules.states(user_id) if s.enabled}
        return [tool for module_id, tool in self._tools.values() if module_id in enabled]

    async def call(
        self,
        user_id: uuid.UUID,
        name: str,
        arguments: dict[str, Any],
        ip: str | None = None,
        *,
        origin: str | None = None,
    ) -> ToolResult:
        """Execute un outil read ; met un outil write ou sensitive en attente de confirmation."""
        with _TRACER.start_as_current_span("tool.call", attributes={"lorakus.tool": name}) as span:
            result = await self._call(user_id, name, arguments, ip, origin)
            span.set_attribute(
                "lorakus.tool.outcome", "pending" if result.confirmation_id else "done"
            )
            return result

    async def _call(
        self,
        user_id: uuid.UUID,
        name: str,
        arguments: dict[str, Any],
        ip: str | None,
        origin: str | None,
    ) -> ToolResult:
        tool, validated = await self._prepare(user_id, name, arguments)
        if tool.risk == "read":
            result = await self._execute(user_id, tool, validated, ip, origin)
            return ToolResult(tool.name, result)
        if tool.summary is None:  # impossible : ToolSpec l'exige pour write et sensitive
            raise ToolError(f"outil {tool.name} : carte non decrite")
        confirmation_id = uuid.uuid4()
        expires_at = datetime.now(UTC) + CONFIRMATION_TTL
        async with self._db.transaction(user_id) as session:
            context = ToolCall(user_id, session, self._ports, origin)
            summary = _clean_summary(await tool.summary(context, validated))
            await session.execute(
                insert(ToolConfirmation).values(
                    id=confirmation_id,
                    user_id=user_id,
                    tool=tool.name,
                    arguments=validated.model_dump(mode="json"),
                    origin=origin,
                    expires_at=expires_at,
                )
            )
            await audit(session, user_id, "tools.request", "success", ip, {"tool": tool.name})
        return ToolResult(
            tool.name,
            confirmation_id=confirmation_id,
            risk=tool.risk,
            summary=summary,
            expires_at=expires_at,
        )

    async def risk_of_confirmation(self, user_id: uuid.UUID, confirmation_id: uuid.UUID) -> str:
        async with self._db.transaction(user_id) as session:
            name = await session.scalar(
                select(ToolConfirmation.tool).where(ToolConfirmation.id == confirmation_id)
            )
        if name is None or name not in self._tools:
            raise ToolError("confirmation inconnue")
        return self._tools[name][1].risk

    async def confirm(
        self, user_id: uuid.UUID, confirmation_id: uuid.UUID, ip: str | None = None
    ) -> ToolResult:
        """Execute une action confirmee : une seule fois, avant expiration, arguments d'origine.

        Reservation, execution et audit dans la meme transaction (voir l'en-tete du fichier).
        """
        with _TRACER.start_as_current_span("tool.confirm"):
            return await self._confirm(user_id, confirmation_id, ip)

    async def _confirm(
        self, user_id: uuid.UUID, confirmation_id: uuid.UUID, ip: str | None
    ) -> ToolResult:
        async with self._db.transaction(user_id) as session:
            # FOR UPDATE : un second clic simultane attend ici, puis ne trouve plus la ligne libre.
            row = (
                await session.execute(
                    select(
                        ToolConfirmation.tool, ToolConfirmation.arguments, ToolConfirmation.origin
                    )
                    .where(
                        ToolConfirmation.id == confirmation_id,
                        ToolConfirmation.used_at.is_(None),
                        ToolConfirmation.cancelled_at.is_(None),
                        ToolConfirmation.expires_at > func.now(),
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise ToolError("Cette action n'est plus disponible (déjà traitée ou expirée).")
            tool, validated = await self._prepare(user_id, row.tool, dict(row.arguments))
            result = await self._run(session, user_id, tool, validated, ip, row.origin)
            await session.execute(
                update(ToolConfirmation)
                .where(ToolConfirmation.id == confirmation_id)
                .values(used_at=func.now(), arguments={})
            )
        return ToolResult(tool.name, result, risk=tool.risk)

    async def cancel(
        self, user_id: uuid.UUID, confirmation_id: uuid.UUID, ip: str | None = None
    ) -> None:
        """Annule une action en attente : elle ne pourra plus etre confirmee."""
        async with self._db.transaction(user_id) as session:
            name = await session.scalar(
                update(ToolConfirmation)
                .where(
                    ToolConfirmation.id == confirmation_id,
                    ToolConfirmation.used_at.is_(None),
                    ToolConfirmation.cancelled_at.is_(None),
                )
                .values(cancelled_at=func.now(), arguments={})
                .returning(ToolConfirmation.tool)
            )
            if name is None:
                raise ToolError("Cette action n'est plus disponible (déjà traitée ou annulée).")
            await audit(session, user_id, "tools.cancel", "success", ip, {"tool": name})

    async def statuses(
        self, user_id: uuid.UUID, confirmation_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, ConfirmationStatus]:
        """Etat de chaque confirmation (celles d'un autre utilisateur sont invisibles : RLS)."""
        if not confirmation_ids:
            return {}
        async with self._db.transaction(user_id) as session:
            rows = await session.execute(
                select(
                    ToolConfirmation.id,
                    ToolConfirmation.used_at,
                    ToolConfirmation.cancelled_at,
                    ToolConfirmation.expires_at <= func.now(),
                ).where(ToolConfirmation.id.in_(list(confirmation_ids)))
            )
            found: dict[uuid.UUID, ConfirmationStatus] = {}
            for confirmation_id, used_at, cancelled_at, expired in rows:
                if used_at is not None:
                    found[confirmation_id] = "confirmed"
                elif cancelled_at is not None:
                    found[confirmation_id] = "cancelled"
                elif expired:
                    found[confirmation_id] = "expired"
                else:
                    found[confirmation_id] = "pending"
            return found

    async def retire_origin(self, user_id: uuid.UUID, origin: str) -> None:
        """Source supprimee (ex. une conversation) : ses actions en attente sont annulees et
        les arguments de toutes ses confirmations effaces. Le reste (outil, issue) demeure."""
        async with self._db.transaction(user_id) as session:
            await session.execute(
                update(ToolConfirmation)
                .where(
                    ToolConfirmation.origin == origin,
                    ToolConfirmation.used_at.is_(None),
                    ToolConfirmation.cancelled_at.is_(None),
                )
                .values(cancelled_at=func.now())
            )
            await session.execute(
                update(ToolConfirmation)
                .where(ToolConfirmation.origin == origin)
                .values(arguments={})
            )

    async def _prepare(
        self, user_id: uuid.UUID, name: str, arguments: dict[str, Any]
    ) -> tuple[ToolSpec, Any]:
        found = self._tools.get(name)
        if found is None or not await self._modules.is_enabled(user_id, found[0]):
            raise ToolError(f"outil indisponible : {name}")
        tool = found[1]
        try:
            return tool, tool.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ToolError(f"arguments invalides : {error.error_count()} erreur(s)") from error

    async def _execute(
        self,
        user_id: uuid.UUID,
        tool: ToolSpec,
        validated: Any,
        ip: str | None,
        origin: str | None,
    ) -> dict[str, Any]:
        async with self._db.transaction(user_id) as session:
            return await self._run(session, user_id, tool, validated, ip, origin)

    async def _run(
        self,
        session: Any,
        user_id: uuid.UUID,
        tool: ToolSpec,
        validated: Any,
        ip: str | None,
        origin: str | None,
    ) -> dict[str, Any]:
        result = await tool.handler(ToolCall(user_id, session, self._ports, origin), validated)
        if len(json.dumps(result, default=str)) > MAX_RESULT_CHARS:
            raise ToolError(f"resultat de {tool.name} trop volumineux")
        await audit(
            session,
            user_id,
            "tools.execute",
            "success",
            ip,
            {"tool": tool.name, "risk": tool.risk},
        )
        return result
