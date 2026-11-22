"""Export des donnees de l'utilisateur (PR 41, SECURITY.md §10).

Un seul fichier JSON avec tout ce que Lorakus garde sur l'utilisateur : son compte, ses
modules, ses souvenirs, sa consommation d'IA, ses cles d'API, son journal de securite, et les
donnees de CHAQUE module qui declare un `data_exporter` dans son manifeste (actif ou non :
desactiver un module ne supprime pas ses donnees).

Jamais dans l'export : empreinte du mot de passe, secret et codes de double authentification,
jetons de session, empreintes des cles d'API, vecteurs des souvenirs. Les requetes ne lisent
que des colonnes nommees ici (jamais une ligne entiere), sous la RLS de l'utilisateur.

Le Core n'importe aucun module : il appelle les exportateurs declares, qui recoivent un
DataExportContext (utilisateur et transaction liee a lui) et rendent un objet JSON.
"""

import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Final

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus import __version__
from lorakus.ai.models import AIUsage
from lorakus.core.account.service import timezone_name
from lorakus.core.identity.models import ApiKey, AuditEvent, BackupCode, Totp, User
from lorakus.core.identity.service import CurrentUser, audit
from lorakus.core.memory.models import MemoryRejection
from lorakus.core.memory.service import MemoryService
from lorakus.core.modules.service import ModuleService
from lorakus.core.planning.models import AgendaEntry, PlanningDay, Task
from lorakus.core.preparations.models import PreparationRow
from lorakus.core.signals.models import InterventionRow, PushSubscriptionRow, SignalRow
from lorakus.core.signals.webpush import push_host
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.data")

FORMAT_VERSION: Final = 1


@dataclass(frozen=True)
class DataExportContext:
    """Ce que recoit l'exportateur d'un module : l'utilisateur, et une transaction liee a lui
    (RLS : le module ne peut lire que les lignes de cet utilisateur)."""

    user_id: uuid.UUID
    open_transaction: Callable[[], AbstractAsyncContextManager[AsyncSession]]


# Signature attendue de ModuleManifest.data_exporter (type libre dans le manifeste).
DataExporter = Callable[[DataExportContext], Awaitable[dict[str, Any]]]


def jsonable(value: Any) -> Any:
    """Valeur prete pour json.dumps (dates ISO 8601, identifiants, montants en texte)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}  # type: ignore[misc]
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]  # type: ignore[misc]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal | IPv4Address | IPv6Address):
        return str(value)
    return value


def _source(source_ref: str | None) -> str | None:
    """Provenance d'un souvenir sans son detail interne (conversation:<id>#<message>)."""
    return source_ref.split("#", 1)[0] if source_ref else None


class DataExportService:
    def __init__(self, database: Database, modules: ModuleService, memory: MemoryService) -> None:
        self._db = database
        self._modules = modules
        self._memory = memory

    async def export(self, user: CurrentUser, ip: str | None = None) -> dict[str, Any]:
        """Toutes les donnees de l'utilisateur, puis l'export est inscrit au journal."""
        data: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "lorakus_version": __version__,
            "generated_at": datetime.now(UTC),
            "account": await self._account(user),
            "modules": await self._module_states(user.id),
            "memory": await self._memory_data(user.id),
            "planning": await self._planning_data(user.id),
            "notifications": await self._notifications_data(user.id),
            **await self._identity_data(user.id),
            "modules_data": await self._modules_data(user.id),
        }
        async with self._db.transaction(user.id) as session:
            await audit(
                session,
                user.id,
                "data.export",
                "success",
                ip,
                {"modules": sorted(data["modules_data"])},
            )
        return jsonable(data)

    async def _account(self, user: CurrentUser) -> dict[str, Any]:
        async with self._db.transaction(user.id) as session:
            row = (
                await session.execute(
                    select(User.email, User.role, User.created_at, User.password_changed_at).where(
                        User.id == user.id
                    )
                )
            ).one()
            totp = await session.scalar(select(Totp.confirmed_at).where(Totp.user_id == user.id))
            codes = await session.scalar(
                select(func.count()).select_from(BackupCode).where(BackupCode.used_at.is_(None))
            )
            tz = await timezone_name(session)
        return {
            "id": user.id,
            "email": row.email,
            "role": row.role,
            "created_at": row.created_at,
            "password_changed_at": row.password_changed_at,
            "second_factor_enabled": totp is not None,
            "backup_codes_remaining": codes or 0,
            "timezone": tz,
        }

    async def _module_states(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "id": state.manifest.id,
                "name": state.manifest.name,
                "enabled": state.enabled,
                "config": state.config,
            }
            for state in await self._modules.states(user_id)
        ]

    async def _memory_data(self, user_id: uuid.UUID) -> dict[str, Any]:
        facts = await self._memory.list_facts(user_id)
        async with self._db.transaction(user_id) as session:
            rejected = await session.scalar(select(func.count()).select_from(MemoryRejection))
        return {
            "facts": [
                {
                    "id": f.id,
                    "content": f.content,
                    "category": f.category,
                    "status": f.status,
                    "source_kind": f.source_kind,
                    "source": _source(f.source_ref),
                    "evidence": f.evidence,
                    "created_at": f.created_at,
                    "confirmed_at": f.confirmed_at,
                }
                for f in facts
            ],
            "settings": {
                "propose_after_conversations": await self._memory.proposals_enabled(user_id)
            },
            # Le texte d'une proposition refusee est efface (seule son empreinte reste).
            "rejected_proposals": rejected or 0,
        }

    async def _planning_data(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Taches et creneaux (PR 44), colonnes nommees une a une."""
        async with self._db.transaction(user_id) as session:
            tasks = (
                (
                    await session.execute(
                        select(
                            Task.id,
                            Task.parent_id,
                            Task.title,
                            Task.notes,
                            Task.status,
                            Task.priority,
                            Task.due_on,
                            Task.estimate_minutes,
                            Task.estimate_source,
                            Task.actual_minutes,
                            Task.owner_module,
                            Task.owner_ref,
                            Task.source_kind,
                            Task.source_ref,
                            Task.created_at,
                            Task.completed_at,
                        ).order_by(Task.created_at, Task.id)
                    )
                )
                .mappings()
                .all()
            )
            agenda = (
                (
                    await session.execute(
                        select(
                            AgendaEntry.title,
                            AgendaEntry.location,
                            AgendaEntry.starts_at,
                            AgendaEntry.ends_at,
                            AgendaEntry.start_date,
                            AgendaEntry.end_date,
                            AgendaEntry.owner_module,
                            AgendaEntry.source_key,
                        ).order_by(AgendaEntry.starts_at, AgendaEntry.start_date)
                    )
                )
                .mappings()
                .all()
            )
            days = (
                (
                    await session.execute(
                        select(
                            PlanningDay.day,
                            PlanningDay.off,
                            PlanningDay.starts_at,
                            PlanningDay.ends_at,
                            PlanningDay.breaks,
                            PlanningDay.source_ref,
                            PlanningDay.updated_at,
                        ).order_by(PlanningDay.day)
                    )
                )
                .mappings()
                .all()
            )
        return {
            "tasks": [{**row, "source_ref": _source(row["source_ref"])} for row in tasks],
            "agenda": [dict(row) for row in agenda],
            # Cadres des jours donnes par l'utilisateur (PR 49).
            "days": [{**row, "source_ref": _source(row["source_ref"])} for row in days],
        }

    async def _notifications_data(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Preparations (briefings), signaux, decisions et appareils (P5, ADR 0028 et 0042).
        Jamais l'adresse d'abonnement ni
        les cles d'un appareil : seulement son nom et le domaine de son service."""
        async with self._db.transaction(user_id) as session:
            signals = (
                (
                    await session.execute(
                        select(
                            SignalRow.id,
                            SignalRow.name,
                            SignalRow.title,
                            SignalRow.body,
                            SignalRow.firm_body,
                            SignalRow.rule,
                            SignalRow.facts,
                            SignalRow.status,
                            SignalRow.outcome,
                            SignalRow.not_before,
                            SignalRow.expires_at,
                            SignalRow.seen_at,
                            SignalRow.closed_at,
                            SignalRow.snoozed_until,
                            SignalRow.created_at,
                        ).order_by(SignalRow.created_at, SignalRow.id)
                    )
                )
                .mappings()
                .all()
            )
            interventions = (
                (
                    await session.execute(
                        select(
                            InterventionRow.signal_id,
                            InterventionRow.level,
                            InterventionRow.channel,
                            InterventionRow.reason,
                            InterventionRow.delivered,
                            InterventionRow.failed,
                            InterventionRow.created_at,
                        ).order_by(InterventionRow.created_at, InterventionRow.level)
                    )
                )
                .mappings()
                .all()
            )
            devices = (
                (
                    await session.execute(
                        select(
                            PushSubscriptionRow.label,
                            PushSubscriptionRow.endpoint,
                            PushSubscriptionRow.created_at,
                            PushSubscriptionRow.last_success_at,
                        ).order_by(PushSubscriptionRow.created_at)
                    )
                )
                .mappings()
                .all()
            )
            preparations = (
                (
                    await session.execute(
                        select(
                            PreparationRow.module,
                            PreparationRow.kind,
                            PreparationRow.day,
                            PreparationRow.title,
                            PreparationRow.sections,
                            PreparationRow.status,
                            PreparationRow.prepared_at,
                            PreparationRow.expires_at,
                            PreparationRow.consulted_at,
                        ).order_by(PreparationRow.day, PreparationRow.kind)
                    )
                )
                .mappings()
                .all()
            )
        return {
            "preparations": [dict(row) for row in preparations],
            "signals": [dict(row) for row in signals],
            "interventions": [dict(row) for row in interventions],
            "devices": [
                {
                    "label": row["label"],
                    "service": push_host(row["endpoint"]),
                    "created_at": row["created_at"],
                    "last_success_at": row["last_success_at"],
                }
                for row in devices
            ],
        }

    async def _identity_data(self, user_id: uuid.UUID) -> dict[str, Any]:
        async with self._db.transaction(user_id) as session:
            usage = (
                (
                    await session.execute(
                        select(
                            AIUsage.task,
                            func.count().label("calls"),
                            func.sum(AIUsage.input_tokens).label("input_tokens"),
                            func.sum(AIUsage.output_tokens).label("output_tokens"),
                            func.sum(AIUsage.cost_usd).label("cost_usd"),
                            func.min(AIUsage.created_at).label("first_call"),
                            func.max(AIUsage.created_at).label("last_call"),
                        )
                        .group_by(AIUsage.task)
                        .order_by(AIUsage.task)
                    )
                )
                .mappings()
                .all()
            )
            keys = (
                (
                    await session.execute(
                        select(
                            ApiKey.name,
                            ApiKey.prefix,
                            ApiKey.scopes,
                            ApiKey.created_at,
                            ApiKey.expires_at,
                            ApiKey.last_used_at,
                            ApiKey.revoked_at,
                        ).order_by(ApiKey.created_at)
                    )
                )
                .mappings()
                .all()
            )
            events = (
                (
                    await session.execute(
                        select(
                            AuditEvent.occurred_at,
                            AuditEvent.action,
                            AuditEvent.outcome,
                            AuditEvent.ip,
                            AuditEvent.details,
                        ).order_by(AuditEvent.id)
                    )
                )
                .mappings()
                .all()
            )
        return {
            "ai_usage": [dict(row) for row in usage],
            "api_keys": [dict(row) for row in keys],
            "security_log": [dict(row) for row in events],
        }

    async def _modules_data(self, user_id: uuid.UUID) -> dict[str, Any]:
        context = DataExportContext(user_id, lambda: self._db.transaction(user_id))
        exported: dict[str, Any] = {}
        for manifest in self._modules.registry:
            exporter: DataExporter | None = manifest.data_exporter
            if exporter is not None:
                exported[manifest.id] = await exporter(context)
        return exported
