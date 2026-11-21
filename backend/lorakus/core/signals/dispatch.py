"""Traitement des signaux dus (ADR 0042) : un seul job pour tous les utilisateurs.

Chaque minute, `signals.dispatch` reserve les signaux dont le prochain examen est du
(fonction SECURITY DEFINER, qui ne rend que des identifiants), puis, pour chacun, sous la RLS
de son utilisateur :

1. verifie que la cause existe encore (module toujours active, tache toujours ouverte) ;
2. rassemble ce qu'il faut a la politique (cadre du jour, budget, appareils) ;
3. applique la decision : carte (niveau 1), notification (niveau 2), attente, fin, expiration.

Jamais deux fois la meme notification : la decision d'envoyer est enregistree (une ligne par
niveau et par signal, unique) et validee AVANT l'envoi ; si deux processus decidaient en meme
temps, le second se heurterait a la contrainte et n'enverrait rien. Un envoi interrompu n'est
pas repris : mieux vaut un rappel manque qu'un rappel en double (la carte, elle, reste).

Aucun appel a un modele de langage : les rappels continuent si le fournisseur d'IA est coupe
(scenario 8).
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol

import structlog
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import day_bounds, local_today
from lorakus.core.account.service import user_timezone
from lorakus.core.modules.models import UserModule
from lorakus.core.outbound import OutboundError, OutboundHttp, PostResult
from lorakus.core.planning.days import current_day, get_frame
from lorakus.core.signals.models import InterventionRow, PushSubscriptionRow, SignalRow
from lorakus.core.signals.policy import TEST_SIGNAL, Decision, SignalState, Surroundings, decide
from lorakus.core.signals.service import open_tasks_among, task_ref
from lorakus.core.signals.webpush import VapidKeys, check_endpoint, encrypt
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.signals")

CLAIM_BATCH: Final = 100
LEASE: Final = timedelta(minutes=2)
MAX_TTL_S: Final = 24 * 3600

INTERVENTIONS = Counter(
    "lorakus_interventions_total", "Interventions decidees", ["level", "reason"]
)
DUPLICATES = Counter(
    "lorakus_interventions_duplicate_total",
    "Interventions refusees par la contrainte d'unicite (doublon evite ; attendu : 0)",
)
PUSHES = Counter(
    "lorakus_push_sent_total",
    "Notifications envoyees, par issue (ok, gone : appareil desabonne, failed, error)",
    ["outcome"],
)
LAST_RUN = Gauge(
    "lorakus_signals_dispatch_last_run_timestamp_seconds", "Dernier passage de signals.dispatch"
)


class Pusher(Protocol):
    """Envoi d'une notification chiffree a un appareil (remplace dans les tests)."""

    async def send(self, device: PushSubscriptionRow, payload: dict[str, Any], ttl_s: int) -> int:
        """Statut HTTP rendu par le service de notification ; OutboundError si transport."""
        ...


@dataclass(frozen=True)
class WebPusher:
    """Envoi reel : chiffrement RFC 8291, jeton VAPID, client sortant protege (SSRF)."""

    keys: VapidKeys
    subject: str
    http: OutboundHttp

    async def send(self, device: PushSubscriptionRow, payload: dict[str, Any], ttl_s: int) -> int:
        endpoint = check_endpoint(device.endpoint)
        body = encrypt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
            device.p256dh,
            device.auth,
        )
        result: PostResult = await self.http.post(
            endpoint,
            body,
            [
                ("Authorization", self.keys.authorization(endpoint, self.subject)),
                ("Content-Type", "application/octet-stream"),
                ("Content-Encoding", "aes128gcm"),
                ("TTL", str(ttl_s)),
                ("Urgency", "normal"),
            ],
        )
        return result.status


async def claim_due(
    database: Database, now: datetime, limit: int = CLAIM_BATCH
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with database.transaction(None) as session:
        rows = await session.execute(
            text("SELECT id, user_id FROM lorakus.core_signals_claim_due(:now, :limit, :lease)"),
            {"now": now, "limit": limit, "lease": LEASE},
        )
        return [(row[0], row[1]) for row in rows]


async def dispatch_due(
    database: Database, pusher: Pusher | None, now: datetime, limit: int = CLAIM_BATCH
) -> dict[str, int]:
    """Tout ce qui est du maintenant ; rend les issues comptees. Un signal en echec
    n'empeche jamais les suivants (son bail expire seul, il sera repris)."""
    outcomes: dict[str, int] = {}
    for signal_id, user_id in await claim_due(database, now, limit):
        try:
            outcome = await process(database, pusher, signal_id, user_id, now)
        except Exception:
            log.exception("signal_dispatch_crashed", signal=str(signal_id))
            outcome = "crashed"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    LAST_RUN.set_to_current_time()
    return outcomes


async def _state(session: AsyncSession, row: SignalRow) -> SignalState:
    result = await session.execute(
        select(InterventionRow.level, InterventionRow.created_at).where(
            InterventionRow.signal_id == row.id
        )
    )
    levels = {level: created for level, created in result}
    return SignalState(
        name=row.name,
        data_class=row.data_class,
        not_before=row.not_before,
        expires_at=row.expires_at,
        seen_at=row.seen_at,
        closed_at=row.closed_at,
        snoozed_until=row.snoozed_until,
        level1_at=levels.get(1),
        level2_done=2 in levels,
    )


async def _surroundings(session: AsyncSession, now: datetime) -> Surroundings:
    tz = await user_timezone(session)
    day = await current_day(session, now, tz)
    start, next_day = day_bounds(local_today(now, tz), tz)
    pushes = await session.scalar(
        select(func.count())
        .select_from(InterventionRow)
        .join(SignalRow, SignalRow.id == InterventionRow.signal_id)
        .where(
            InterventionRow.level == 2,
            InterventionRow.created_at >= start,
            InterventionRow.created_at < next_day,
            SignalRow.name != TEST_SIGNAL,
        )
    )
    devices = await session.scalar(select(func.count()).select_from(PushSubscriptionRow))
    return Surroundings(
        frame=await get_frame(session, day),
        next_day_start=next_day,
        pushes_today=pushes or 0,
        devices=devices or 0,
    )


async def _gone(session: AsyncSession, row: SignalRow) -> str | None:
    """Raison de retirer un signal dont la cause n'existe plus, ou None."""
    if row.module != "core":
        enabled = await session.scalar(
            select(UserModule.enabled).where(UserModule.module_id == row.module)
        )
        if not enabled:
            return "module_disabled"
    ref = task_ref(row.subject_ref)
    if ref is not None and not await open_tasks_among(session, {ref}):
        return "subject_gone"
    return None


def _record(decision: Decision, around: Surroundings) -> dict[str, Any]:
    """Ce qui justifie la decision, pour « Pourquoi ? » : jamais un texte de l'utilisateur."""
    frame = around.frame
    return {
        "reason": decision.reason,
        "pushes_today": around.pushes_today,
        "devices": around.devices,
        "frame": None
        if frame is None
        else {
            "off": frame.off,
            "start": frame.start.isoformat() if frame.start else None,
            "end": frame.end.isoformat() if frame.end else None,
        },
    }


async def _intervene(
    session: AsyncSession,
    row: SignalRow,
    level: int,
    decision: Decision,
    record: dict[str, Any],
    now: datetime,
) -> uuid.UUID | None:
    """Enregistre la decision ; None si ce niveau existait deja pour ce signal (doublon)."""
    created = await session.scalar(
        insert(InterventionRow)
        .values(
            id=uuid.uuid4(),
            user_id=row.user_id,
            signal_id=row.id,
            level=level,
            channel="app" if level == 1 else "push",
            reason=decision.reason,
            decision=record,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_core_interventions_signal_id_level")
        .returning(InterventionRow.id)
    )
    if created is None:
        DUPLICATES.inc()
        log.warning("intervention_duplicate_refused", signal=str(row.id), level=level)
        return None
    INTERVENTIONS.labels(level=str(level), reason=decision.reason).inc()
    return created


def _settle(row: SignalRow, decision: Decision) -> None:
    """Etat du signal apres une decision qui n'envoie rien."""
    row.locked_until = None
    if decision.action == "wait":
        row.next_check_at = decision.next_check
        row.outcome = decision.reason
    elif decision.action in ("done", "expire"):
        row.status = "expired" if decision.action == "expire" else "done"
        row.outcome = decision.reason
        row.next_check_at = None


async def process(
    database: Database,
    pusher: Pusher | None,
    signal_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime,
) -> str:
    """Examine un signal ; rend l'issue (pour les metriques)."""
    async with database.transaction(user_id) as session:
        row = await session.scalar(
            select(SignalRow).where(SignalRow.id == signal_id).with_for_update()
        )
        if row is None or row.status != "active":
            return "skipped"
        gone = await _gone(session, row)
        if gone is not None:
            row.status, row.outcome = "withdrawn", gone
            row.next_check_at = row.locked_until = None
            return gone
        around = await _surroundings(session, now)
        if pusher is None:  # notifications non configurees ici (developpement)
            around = Surroundings(around.frame, around.next_day_start, around.pushes_today, 0)
        decision = decide(await _state(session, row), around, now)
        if decision.action == "app":
            await _intervene(session, row, 1, decision, _record(decision, around), now)
            # Decision suivante tout de suite (le plus souvent : attendre 24 h).
            decision = decide(await _state(session, row), around, now)
        if decision.action != "push":
            _settle(row, decision)
            return decision.reason
        intervention = await _intervene(session, row, 2, decision, _record(decision, around), now)
        devices = list(await session.scalars(select(PushSubscriptionRow)))
        payload = {
            "title": row.title,
            "body": row.firm_body or row.body,
            "url": f"{row.url}?signal={row.id}",
            "tag": str(row.id),
        }
        ttl = max(60, min(MAX_TTL_S, int((row.expires_at - now).total_seconds())))
        row.locked_until = None
        # Notification de test : fini apres l'envoi. Sinon, plus rien a decider (une par cause).
        row.status, row.outcome, row.next_check_at = "done", decision.reason, None
    if intervention is None or pusher is None:
        return "duplicate"
    # Decision enregistree et validee : l'envoi se fait hors de la transaction.
    results = await _send_all(pusher, devices, payload, ttl)
    async with database.transaction(user_id) as session:
        await _account(session, intervention, results, now)
    return decision.reason


async def _send_all(
    pusher: Pusher, devices: Sequence[PushSubscriptionRow], payload: dict[str, Any], ttl: int
) -> dict[uuid.UUID, str]:
    results: dict[uuid.UUID, str] = {}
    for device in devices:
        try:
            status = await pusher.send(device, payload, ttl)
        except OutboundError as error:
            log.warning("push_transport_failed", reason=error.reason)
            results[device.id] = "error"
            continue
        except ValueError:  # adresse ou cles devenues invalides
            results[device.id] = "gone"
            continue
        if 200 <= status < 300:
            results[device.id] = "ok"
        elif status in (404, 410):  # abonnement expire ou retire par le navigateur
            results[device.id] = "gone"
        else:
            log.warning("push_refused", status=status)
            results[device.id] = "failed"
    return results


async def _account(
    session: AsyncSession, intervention: uuid.UUID, results: dict[uuid.UUID, str], now: datetime
) -> None:
    """Bilan de l'envoi : intervention, appareils (un appareil desabonne est oublie)."""
    for device_id, outcome in results.items():
        PUSHES.labels(outcome=outcome).inc()
        device = await session.get(PushSubscriptionRow, device_id)
        if device is None:
            continue
        if outcome == "gone":
            await session.delete(device)
        elif outcome == "ok":
            device.last_success_at, device.failures = now, 0
        else:
            device.last_failure_at, device.failures = now, device.failures + 1
    row = await session.get(InterventionRow, intervention)
    if row is not None:
        row.delivered = sum(1 for o in results.values() if o == "ok")
        row.failed = sum(1 for o in results.values() if o != "ok")
