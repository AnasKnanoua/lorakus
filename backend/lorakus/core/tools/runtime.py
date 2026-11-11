"""Execution des outils : validation, confirmation, audit (ADR 0012)."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from lorakus.core.identity.service import audit
from lorakus.core.modules.service import ModuleService
from lorakus.core.tools.models import ToolConfirmation
from lorakus.core.tools.spec import MAX_RESULT_CHARS, ToolCall, ToolSpec
from lorakus.db.database import Database

CONFIRMATION_TTL: Final = timedelta(minutes=10)


class ToolError(Exception):
    """Appel refuse : outil inconnu ou indisponible, arguments invalides, confirmation perimee."""


@dataclass(frozen=True)
class ToolResult:
    """Resultat d'un appel : execute (result) ou en attente de confirmation (confirmation_id)."""

    tool: str
    result: dict[str, Any] | None = None
    confirmation_id: uuid.UUID | None = None
    risk: str = "read"


class ToolRuntime:
    """Point de passage unique de toute action, qu'elle vienne de l'API ou, plus tard, d'un LLM."""

    def __init__(self, database: Database, modules: ModuleService) -> None:
        self._db = database
        self._modules = modules
        self._tools: dict[str, tuple[str, ToolSpec]] = {
            tool.name: (manifest.id, tool)
            for manifest in modules.registry
            for tool in manifest.tools
        }

    async def available(self, user_id: uuid.UUID) -> list[ToolSpec]:
        enabled = {s.manifest.id for s in await self._modules.states(user_id) if s.enabled}
        return [tool for module_id, tool in self._tools.values() if module_id in enabled]

    async def call(
        self, user_id: uuid.UUID, name: str, arguments: dict[str, Any], ip: str | None = None
    ) -> ToolResult:
        """Execute un outil read ; met un outil write ou sensitive en attente de confirmation."""
        tool, validated = await self._prepare(user_id, name, arguments)
        if tool.risk == "read":
            return ToolResult(tool.name, await self._execute(user_id, tool, validated, ip))
        confirmation_id = uuid.uuid4()
        async with self._db.transaction(user_id) as session:
            await session.execute(
                insert(ToolConfirmation).values(
                    id=confirmation_id,
                    user_id=user_id,
                    tool=tool.name,
                    arguments=validated.model_dump(mode="json"),
                    expires_at=datetime.now(UTC) + CONFIRMATION_TTL,
                )
            )
            await audit(session, user_id, "tools.request", "success", ip, {"tool": tool.name})
        return ToolResult(tool.name, confirmation_id=confirmation_id, risk=tool.risk)

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
        """Execute une action confirmee : une seule fois, avant expiration, arguments d'origine."""
        async with self._db.transaction(user_id) as session:
            row = (
                await session.execute(
                    update(ToolConfirmation)
                    .where(
                        ToolConfirmation.id == confirmation_id,
                        ToolConfirmation.used_at.is_(None),
                        ToolConfirmation.expires_at > func.now(),
                    )
                    .values(used_at=func.now())
                    .returning(ToolConfirmation.tool, ToolConfirmation.arguments)
                )
            ).one_or_none()
        if row is None:
            raise ToolError("confirmation inconnue, deja utilisee ou expiree")
        tool, validated = await self._prepare(user_id, row.tool, dict(row.arguments))
        return ToolResult(
            tool.name, await self._execute(user_id, tool, validated, ip), risk=tool.risk
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
        self, user_id: uuid.UUID, tool: ToolSpec, validated: Any, ip: str | None
    ) -> dict[str, Any]:
        async with self._db.transaction(user_id) as session:
            result = await tool.handler(ToolCall(user_id=user_id, session=session), validated)
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
