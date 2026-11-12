"""ModelRouter : seul point de passage vers un fournisseur d'IA (ADR 0006, 0007).

Pour chaque demande, dans cet ordre, avant de payer quoi que ce soit :

1. `no_ai` : refus (donnee dont la source interdit tout usage IA, ex. Strava).
2. Coupure generale (`ai_kill_switch`) : indisponible.
3. Prompt trop long pour la tache : refus (on ne paie jamais le palier superieur).
4. Fournisseurs autorises pour la classe de donnees : un fournisseur externe ne recoit
   jamais `sensitive`, quoi que dise routing.toml.
5. Plafond mensuel de l'utilisateur : indisponible s'il est atteint.
6. Rythme de l'utilisateur (PR 35) : reponses simultanees, appels par minute et par jour ;
   indisponible au-dela (une rafale ne peut pas vider le budget en quelques secondes).

Puis les cibles de la chaine sont essayees dans l'ordre. Tant qu'aucun texte n'a ete
transmis, une panne fait passer a la cible suivante ; apres le premier morceau, la
reponse ne peut plus changer de modele et l'interruption est signalee a l'appelant.

Les exceptions AIRefusedError et AIUnavailableError ne sont pas des erreurs du programme :
l'appelant repond alors par un gabarit (scenario 8 du MVP).
"""

import time
import uuid
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, NoReturn, Protocol

import structlog

from lorakus.ai.breaker import CircuitBreaker
from lorakus.ai.catalog import Catalog, split_target
from lorakus.ai.port import (
    DATA_CLASS_RANK,
    AIProvider,
    ChatRequest,
    Completion,
    DataClass,
    ProviderError,
    TextDelta,
    Usage,
    estimate_tokens,
)
from lorakus.ai.usage import UsageLedger
from lorakus.observability.metrics import (
    AI_COST,
    AI_FIRST_TOKEN,
    AI_REFUSALS,
    AI_REQUESTS,
    AI_TOKENS,
    AI_USAGE_RECORD_FAILURES,
)

log = structlog.get_logger("lorakus.ai")

BUDGET_WARNING_RATIO: Final = Decimal("0.8")

RefusalReason = Literal["no_ai", "data_class", "too_long"]
UnavailableReason = Literal["kill_switch", "budget", "no_provider", "rate_limited"]


class AIRefusedError(Exception):
    """Demande refusee par une regle : la reessayer telle quelle donnerait le meme refus."""

    def __init__(self, reason: RefusalReason) -> None:
        super().__init__(reason)
        self.reason: RefusalReason = reason


class AIUnavailableError(Exception):
    """Aucune IA utilisable pour l'instant (coupure, budget atteint, fournisseurs en panne)."""

    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason)
        self.reason: UnavailableReason = reason


class AIInterruptedError(Exception):
    """Le fournisseur a echoue apres avoir commence a repondre : reponse incomplete."""


@dataclass(frozen=True)
class ChatResult:
    """Dernier evenement d'un flux reussi."""

    provider: str
    model: str
    usage: Usage
    cost_usd: Decimal
    budget_warning: bool  # 80 % du plafond mensuel atteint avec cet appel


RouterEvent = TextDelta | ChatResult


class CallQuota(Protocol):
    """Rythme des appels d'un utilisateur. Compte l'appel et dit s'il est autorise."""

    async def allow(self, user_id: uuid.UUID) -> bool: ...


def _prompt_tokens(request: ChatRequest) -> int:
    return estimate_tokens(request.system) + sum(
        estimate_tokens(m.content) for m in request.messages
    )


class ModelRouter:
    def __init__(
        self,
        catalog: Catalog,
        providers: Mapping[str, AIProvider],
        usage: UsageLedger,
        *,
        monthly_budget_usd: Decimal,
        kill_switch: bool = False,
        breaker: CircuitBreaker | None = None,
        quota: CallQuota | None = None,
        max_concurrent_per_user: int | None = None,
    ) -> None:
        self._catalog = catalog
        self._providers = dict(providers)
        self._usage = usage
        self._budget = monthly_budget_usd
        self._kill_switch = kill_switch
        self._breaker = breaker or CircuitBreaker()
        self._quota = quota
        self._max_concurrent = max_concurrent_per_user
        # Reponses en cours par utilisateur, dans ce processus (une seule API aujourd'hui).
        self._in_flight: dict[uuid.UUID, int] = {}

    def available_targets(self, task: str, data_class: DataClass) -> list[str]:
        """Cibles de la tache utilisables pour cette classe de donnees, dans l'ordre."""
        targets: list[str] = []
        for target in self._catalog.route(task).chain:
            name, _ = split_target(target)
            provider = self._providers.get(name)
            if provider is None:
                continue  # fournisseur non configure ici (cle absente, fake hors dev)
            if data_class == "sensitive" and provider.capabilities().external:
                continue  # refus structurel : rien de sensible ne quitte le serveur
            allowed = self._catalog.policy(name).max_data_class
            if DATA_CLASS_RANK[data_class] > DATA_CLASS_RANK[allowed]:
                continue
            targets.append(target)
        return targets

    def _refuse(self, task: str, error: AIRefusedError | AIUnavailableError) -> NoReturn:
        AI_REFUSALS.labels(task=task, reason=error.reason).inc()
        log.info("ai_refused", task=task, reason=error.reason)
        raise error

    async def chat_stream(
        self,
        user_id: uuid.UUID,
        *,
        task: str,
        data_class: DataClass,
        request: ChatRequest,
        no_ai: bool = False,
    ) -> AsyncGenerator[RouterEvent]:
        """Reponse en flux : des TextDelta, puis un ChatResult.

        Leve AIRefusedError ou AIUnavailableError avant tout texte, AIInterruptedError si la reponse
        s'arrete en cours de route. Un generateur : l'appelant le ferme (aclose) si le client
        s'en va, ce qui libere le fournisseur et le disjoncteur.
        """
        route = self._catalog.route(task)
        if no_ai:
            self._refuse(task, AIRefusedError("no_ai"))
        if self._kill_switch:
            self._refuse(task, AIUnavailableError("kill_switch"))
        if _prompt_tokens(request) > route.max_input_tokens:
            self._refuse(task, AIRefusedError("too_long"))

        configured = [t for t in route.chain if split_target(t)[0] in self._providers]
        targets = self.available_targets(task, data_class)
        if not configured:
            self._refuse(task, AIUnavailableError("no_provider"))
        if not targets:
            self._refuse(task, AIRefusedError("data_class"))

        spent = await self._usage.month_cost(user_id)
        if spent >= self._budget:
            self._refuse(task, AIUnavailableError("budget"))

        # Le compteur de reponses en cours d'abord : un refus pour cause de reponse deja en
        # cours ne consomme pas le quota par minute.
        in_flight = self._in_flight.get(user_id, 0)
        if self._max_concurrent is not None and in_flight >= self._max_concurrent:
            self._refuse(task, AIUnavailableError("rate_limited"))
        if self._quota is not None and not await self._quota.allow(user_id):
            self._refuse(task, AIUnavailableError("rate_limited"))

        self._in_flight[user_id] = self._in_flight.get(user_id, 0) + 1
        stream = self._stream(user_id, task, data_class, request, targets, spent)
        try:
            async for event in stream:
                yield event
        finally:
            # Ferme le flux interne tout de suite (client parti) : le disjoncteur et le
            # fournisseur sont liberes avant que le compteur ne redescende.
            await stream.aclose()
            remaining = self._in_flight.get(user_id, 1) - 1
            if remaining > 0:
                self._in_flight[user_id] = remaining
            else:
                self._in_flight.pop(user_id, None)

    async def _stream(
        self,
        user_id: uuid.UUID,
        task: str,
        data_class: DataClass,
        request: ChatRequest,
        targets: list[str],
        spent: Decimal,
    ) -> AsyncGenerator[RouterEvent]:
        """Essaie les cibles dans l'ordre (contrats decrits dans chat_stream)."""
        route = self._catalog.route(task)
        bounded = request.model_copy(
            update={"max_output_tokens": min(request.max_output_tokens, route.max_output_tokens)}
        )
        for target in targets:
            name, model = split_target(target)
            if not self._breaker.allows(name):
                continue
            completion: Completion | None = None
            emitted = False
            started = time.monotonic()
            try:
                async for event in self._providers[name].chat_stream(model, bounded):
                    if isinstance(event, TextDelta):
                        if not emitted:
                            emitted = True
                            AI_FIRST_TOKEN.labels(provider=name, model=model).observe(
                                time.monotonic() - started
                            )
                        yield event
                    else:
                        completion = event
                if completion is None:
                    raise ProviderError("unavailable", "flux termine sans fin de reponse")
            except ProviderError as error:
                self._breaker.failure(name)
                outcome = "interrupted" if emitted else "error"
                AI_REQUESTS.labels(task=task, provider=name, model=model, outcome=outcome).inc()
                log.warning("ai_provider_failed", task=task, target=target, kind=error.kind)
                if emitted:
                    raise AIInterruptedError(str(error)) from error
                continue
            except BaseException:
                # Client parti (annulation) ou bogue : pas de verdict sur le fournisseur.
                self._breaker.abandoned(name)
                raise

            self._breaker.success(name)
            duration_ms = int((time.monotonic() - started) * 1000)
            cost = self._catalog.price(target).cost(completion.usage)
            self._observe(task, name, model, completion.usage, cost)
            await self._record(
                user_id, task, name, model, data_class, completion.usage, cost, duration_ms
            )
            log.info(
                "ai_call",
                task=task,
                target=target,
                input_tokens=completion.usage.input_tokens,
                output_tokens=completion.usage.output_tokens,
                cost_usd=str(cost),
                duration_ms=duration_ms,
                stop_reason=completion.stop_reason,
            )
            yield ChatResult(
                provider=name,
                model=model,
                usage=completion.usage,
                cost_usd=cost,
                budget_warning=spent + cost >= self._budget * BUDGET_WARNING_RATIO,
            )
            return

        self._refuse(task, AIUnavailableError("no_provider"))

    @staticmethod
    def _observe(task: str, provider: str, model: str, usage: Usage, cost: Decimal) -> None:
        AI_REQUESTS.labels(task=task, provider=provider, model=model, outcome="ok").inc()
        for kind, count in (
            ("input", usage.input_tokens),
            ("output", usage.output_tokens),
            ("cache_read", usage.cache_read_tokens),
            ("cache_write", usage.cache_write_tokens),
        ):
            AI_TOKENS.labels(provider=provider, model=model, kind=kind).inc(count)
        AI_COST.labels(provider=provider, model=model).inc(float(cost))

    async def _record(
        self,
        user_id: uuid.UUID,
        task: str,
        provider: str,
        model: str,
        data_class: DataClass,
        usage: Usage,
        cost: Decimal,
        duration_ms: int,
    ) -> None:
        # La reponse est deja chez l'utilisateur : un echec d'ecriture ne doit pas la faire
        # echouer, mais il est visible (journal et metrique, alerte en PR 33).
        try:
            await self._usage.record(
                user_id,
                task=task,
                provider=provider,
                model=model,
                data_class=data_class,
                usage=usage,
                cost_usd=cost,
                duration_ms=duration_ms,
            )
        except Exception as error:
            AI_USAGE_RECORD_FAILURES.inc()
            log.error("ai_usage_record_failed", error=type(error).__name__)
