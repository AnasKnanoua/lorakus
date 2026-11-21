"""Le Sergent prend les devants (P5, ADR 0042) : un seul rappel avant une echeance.

Regle (scenario 4) : une tache ouverte a rendre dans 3 jours ou moins, dont aucune etape n'est
terminee, donne UN signal `focus.deadline_soon`. Le Sergent ne notifie jamais lui-meme : la
politique d'intervention du Core montre d'abord une carte (niveau 1), puis, seulement si elle
n'a pas ete vue en 24 h, une notification pendant ta plage de travail (niveau 2).

- Un seul job (`focus.deadline_watch`, toutes les 10 minutes) pour tous les utilisateurs qui
  ont le Sergent active (MODULE_SYSTEM.md §11) ; chacun est traite sous sa propre RLS.
- Une cause = une tache ET son echeance : la cle ne change pas d'un passage a l'autre (aucun
  doublon), et une echeance deplacee est une nouvelle cause.
- Une tache commencee (une etape terminee), terminee, supprimee ou repoussee au-dela de 3 jours
  retire son signal : sa carte disparait.
- « Commencee » ne se voit que par les etapes : sans decoupage, Lorakus ne peut pas savoir que
  tu as commence. La carte se ferme d'un geste (« OK »), et alors rien d'autre ne suit.

Des regles, sans LLM ni table : le rappel part meme si le fournisseur d'IA est coupe.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lorakus.core.account.clock import day_bounds, local_today
from lorakus.core.account.dates import duration, french_date, relative_day
from lorakus.core.account.service import user_timezone
from lorakus.core.jobs.port import JobContext, periodic
from lorakus.core.planning.service import MAX_LIST, TaskView, list_tasks
from lorakus.core.signals.service import Fact, SignalDraft, emit, live_keys, withdraw
from lorakus.db.database import Database

log = structlog.get_logger("lorakus.focus")

SIGNAL: Final = "focus.deadline_soon"
WATCH_DAYS: Final = 3
RULE: Final = (
    "Sergent : une tâche à rendre dans 3 jours ou moins, sans étape terminée, donne un seul "
    "rappel. Une notification ne suit que si ce rappel n'est pas vu en 24 heures, pendant ta "
    "plage de travail, 3 par jour au plus."
)
SOURCES: Final = {"academic": "Cours", "projects": "Projets"}


def started(task: TaskView) -> bool:
    """Une etape au moins est terminee : la tache est commencee."""
    return task.subtasks > task.open_subtasks


def key(task: TaskView, due: date) -> str:
    return f"{SIGNAL}:{task.id}:{due.isoformat()}"


def draft(
    task: TaskView, due: date, today: date, now: datetime, end_of_due_day: datetime
) -> SignalDraft:
    """Le signal d'une tache ; textes ecrits ici, avec la date absolue."""
    days = (due - today).days
    when = relative_day(due, today)
    absolute = french_date(due)
    source = SOURCES.get(task.owner_module or "", "Tâches")
    estimate = duration(task.estimate_minutes) if task.estimate_minutes is not None else "inconnue"
    firm = f"Toujours pas commencé : « {task.title} » est à rendre {when} ({absolute})."
    if task.estimate_minutes is not None:
        firm += f" Il te faut environ {estimate}."
    return SignalDraft(
        name=SIGNAL,
        kind="scheduled",
        # Plus l'echeance est proche, plus la carte passe devant les autres.
        strength=round(1 - days / (WATCH_DAYS + 1), 2),
        data_class="personal",
        dedup_key=key(task, due),
        subject_ref=f"task:{task.id}",
        title=f"À rendre {when}",
        body=f"{task.title} · {absolute}. Pas encore commencé.",
        firm_body=firm + " Ouvre Ma journée pour lui trouver un créneau.",
        rule=RULE,
        url="/today",
        not_before=now,
        expires_at=end_of_due_day,
        facts=(
            Fact("Tâche", task.title, source),
            Fact("Échéance", f"{absolute} ({when})", source),
            Fact("Avancement", "aucune étape terminée", "Planning"),
            Fact(
                "Durée estimée",
                estimate,
                "Planning",
                measured=task.estimate_source != "assistant",
            ),
        ),
    )


async def reconcile(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> dict[str, int]:
    """Met les signaux de l'utilisateur en accord avec ses taches : emet les nouveaux,
    retire ceux qui n'ont plus de raison d'etre. Rejouer ne change rien."""
    tz = await user_timezone(session)
    today = local_today(now, tz)
    wanted: dict[str, tuple[TaskView, date]] = {}
    for task in await list_tasks(session, "open", MAX_LIST):
        due = task.due_on
        if due is None or task.parent_id is not None or started(task):
            continue  # une etape suit sa tache ; sans echeance, rien a rappeler
        if 0 <= (due - today).days <= WATCH_DAYS:
            wanted[key(task, due)] = (task, due)
    counts = {"emitted": 0, "withdrawn": 0}
    for gone in await live_keys(session, "focus", SIGNAL) - wanted.keys():
        if await withdraw(session, "focus", gone, "no_longer_due"):
            counts["withdrawn"] += 1
    for task, due in wanted.values():
        end = day_bounds(due, tz)[1]
        if await emit(session, user_id, "focus", draft(task, due, today, now, end)):
            counts["emitted"] += 1
    return counts


async def watch_deadlines(database: Database, now: datetime) -> dict[str, int]:
    """Tous les utilisateurs concernes, chacun sous sa RLS ; un echec n'arrete pas les autres."""
    # Marge d'un jour : le fuseau de chacun n'est connu qu'une fois sous sa RLS.
    until = now.date() + timedelta(days=WATCH_DAYS + 1)
    async with database.transaction(None) as session:
        users = list(
            await session.scalars(
                text("SELECT user_id FROM lorakus.core_users_with_tasks_due(:until, 'focus')"),
                {"until": until},
            )
        )
    totals = {"users": len(users), "emitted": 0, "withdrawn": 0, "crashed": 0}
    for user in users:
        try:
            async with database.transaction(user) as session:
                counts = await reconcile(session, user, now)
        except Exception:
            log.exception("deadline_watch_crashed")
            totals["crashed"] += 1
            continue
        totals["emitted"] += counts["emitted"]
        totals["withdrawn"] += counts["withdrawn"]
    return totals


@periodic("focus.deadline_watch", cron="*/10 * * * *")
async def deadline_watch(ctx: JobContext, payload: dict[str, Any]) -> None:
    totals = await watch_deadlines(ctx.database, datetime.now(UTC))
    if totals["emitted"] or totals["withdrawn"] or totals["crashed"]:
        log.info("deadline_watch_round", **totals)
