"""Activation et configuration des modules, par utilisateur."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from lorakus.core.identity.service import audit
from lorakus.core.modules.manifest import ModuleManifest
from lorakus.core.modules.models import UserModule
from lorakus.core.modules.registry import ModuleRegistry
from lorakus.db.database import Database


class ModuleStateError(ValueError):
    """Changement refuse (module inconnu, dependance non activee, dependant actif...)."""


class ModuleConfigError(ModuleStateError):
    """Configuration refusee par le schema du module."""


@dataclass(frozen=True)
class ModuleState:
    """Un module et son etat pour un utilisateur."""

    manifest: ModuleManifest
    enabled: bool
    config: dict[str, Any]


class ModuleService:
    """Etat des modules pour chaque utilisateur. Un module desactive n'expose rien."""

    def __init__(self, database: Database, registry: ModuleRegistry) -> None:
        self._db = database
        self.registry = registry

    async def states(self, user_id: uuid.UUID) -> list[ModuleState]:
        async with self._db.transaction(user_id) as session:
            rows = {
                row.module_id: row for row in (await session.execute(select(UserModule))).scalars()
            }
        result: list[ModuleState] = []
        for manifest in self.registry:
            row = rows.get(manifest.id)
            result.append(
                ModuleState(
                    manifest=manifest,
                    enabled=bool(row and row.enabled),
                    config=dict(row.config) if row else {},
                )
            )
        return result

    async def is_enabled(self, user_id: uuid.UUID, module_id: str) -> bool:
        if self.registry.get(module_id) is None:
            return False
        async with self._db.transaction(user_id) as session:
            return bool(
                await session.scalar(
                    select(UserModule.enabled).where(UserModule.module_id == module_id)
                )
            )

    async def set_state(
        self,
        user_id: uuid.UUID,
        module_id: str,
        enabled: bool,
        config: dict[str, Any] | None,
        ip: str | None = None,
    ) -> ModuleState:
        """Active, desactive ou reconfigure un module ; la configuration est validee."""
        manifest = self.registry.get(module_id)
        if manifest is None:
            raise ModuleStateError(f"module inconnu : {module_id}")
        enabled_now = {state.manifest.id for state in await self.states(user_id) if state.enabled}
        if enabled:
            missing = [dep for dep in manifest.depends_on if dep not in enabled_now]
            if missing:
                raise ModuleStateError(f"activer d'abord : {', '.join(missing)}")
        else:
            active_dependents = [
                dep for dep in self.registry.dependents_of(module_id) if dep in enabled_now
            ]
            if active_dependents:
                raise ModuleStateError(f"desactiver d'abord : {', '.join(active_dependents)}")
        try:
            validated = manifest.validate_config(config)
        except ValueError as error:
            raise ModuleConfigError(f"configuration invalide : {error}") from error

        async with self._db.transaction(user_id) as session:
            statement = insert(UserModule).values(
                user_id=user_id, module_id=module_id, enabled=enabled, config=validated
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[UserModule.user_id, UserModule.module_id],
                    set_={"enabled": enabled, "config": validated, "updated_at": func.now()},
                )
            )
            action = "modules.enable" if enabled else "modules.disable"
            await audit(session, user_id, action, "success", ip, {"module": module_id})
        return ModuleState(manifest=manifest, enabled=enabled, config=validated)
