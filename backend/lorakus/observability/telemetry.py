"""Traces et journaux OpenTelemetry (PR 40, ADR 0010 amende).

L'API et le worker envoient eux-memes, en OTLP/HTTP sur le reseau interne :
- leurs TRACES a Tempo (ce qui s'est passe pendant une requete, etape par etape, avec les
  durees : requete HTTP, tour du chat, appels au modele, outils, specialistes, SQL) ;
  les appels au modele sont des spans maison (`ai.call`) : le SDK d'Anthropic utilise httpx2,
  que l'instrumentation httpx officielle ne connait pas ;
- une COPIE de leurs journaux a Loki, avec l'identifiant de la trace en cours : un clic
  dans Grafana mene d'une trace a ses journaux, et inversement.

Pas d'agent (Grafana Alloy) : il aurait du lire le socket Docker, un acces equivalent a root.

Garanties :
- desactive tant qu'aucune adresse n'est configuree (tests, developpement) : rien n'est cree ;
- jamais bloquant : export en arriere-plan, par lots, avec un court delai ; si Tempo ou
  Loki tombe, les donnees sont perdues pour eux, l'application ne le voit pas, et les
  journaux restent sur la sortie standard ;
- aucun contenu personnel : les attributs portant une adresse complete ou une chaine de
  requete (`?q=...` de la recherche) sont nettoyes avant l'export (ScrubbingSpanExporter),
  aucun corps de requete ni en-tete n'est capture, et les requetes SQL n'ont pas leurs
  valeurs. Verifie par un test « canari ».
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Paquet officiel sans annotations de type publiees (pas de py.typed), comme sqlalchemy plus bas.
from opentelemetry.instrumentation.logging.handler import (  # pyright: ignore[reportMissingTypeStubs]
    LoggingHandler,
)
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from sqlalchemy import event
from structlog.typing import EventDict, WrappedLogger

EXPORT_TIMEOUT_S: Final = 2.0

# Attributs qui peuvent porter une chaine de requete ou une adresse complete : la valeur est
# reduite au chemin, ou retiree.
_URL_KEYS: Final = ("http.url", "http.target", "url.full", "http.request.url")
_DROPPED_KEYS: Final = ("url.query", "http.query", "db.query.parameters")


def _strip_query(value: str) -> str:
    if "?" not in value and "#" not in value:
        return value
    if value.startswith("/"):
        return value.split("?", 1)[0].split("#", 1)[0]
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def scrub_attributes(attributes: Any) -> dict[str, Any]:
    """Attributs sans chaine de requete ni parametre SQL (voir l'en-tete)."""
    cleaned: dict[str, Any] = {}
    for key, value in dict(attributes or {}).items():
        if key in _DROPPED_KEYS or key.startswith("http.request.header."):
            continue
        if key in _URL_KEYS and isinstance(value, str):
            cleaned[key] = _strip_query(value)
        else:
            cleaned[key] = value
    return cleaned


class ScrubbingSpanExporter(SpanExporter):
    """Nettoie les attributs de chaque span (et de ses evenements) avant l'export."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([_scrubbed(span) for span in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def _scrubbed(span: ReadableSpan) -> ReadableSpan:
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=scrub_attributes(span.attributes),
        events=span.events,  # evenements : seulement les exceptions (type, pas de valeurs)
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


# Attributs internes de structlog sur chaque LogRecord : inutiles (et bruyants) dans Loki.
_STRUCTLOG_INTERNALS: Final = ("_logger", "_name", "_from_structlog", "_record")


def export_filter(
    formatter: logging.Formatter | None,
) -> Callable[[logging.LogRecord], logging.LogRecord | bool]:
    """Filtre de la copie vers Loki ; la sortie standard n'est pas touchee.

    - Les journaux d'OpenTelemetry lui-meme (ex. « echec d'export ») ne repartent pas vers
      Loki : sinon, Loki en panne produirait des journaux a exporter vers... Loki.
    - La ligne est d'abord mise en forme comme sur la sortie standard (formateur structlog,
      qui a besoin de ses attributs internes), puis c'est une COPIE deja mise en forme, sans
      ces attributs, qui part : Loki recoit exactement la ligne JSON de `docker compose logs`.
    """

    def keep(record: logging.LogRecord) -> logging.LogRecord | bool:
        if record.name.startswith("opentelemetry"):
            return False
        copy = logging.makeLogRecord(record.__dict__)
        if formatter is not None:
            copy.msg = formatter.format(record)
            copy.args = None
            copy.exc_info = None
            copy.exc_text = None
            copy.stack_info = None
        for key in _STRUCTLOG_INTERNALS:
            copy.__dict__.pop(key, None)
        return copy

    return keep


@dataclass
class Telemetry:
    """Ce qui a ete installe, pour le vider proprement a l'arret."""

    tracer_provider: TracerProvider
    logger_provider: LoggerProvider | None
    handler: LoggingHandler | None

    def attach_logging(self) -> None:
        """(Re)branche la copie des journaux sur la journalisation standard, sans doublon.

        configure_logging remplace les gestionnaires : a appeler apres lui (create_app et le
        worker le font dans cet ordre ; les tests qui recreent une application aussi).
        """
        root = logging.getLogger()
        if self.handler is not None and self.handler not in root.handlers:
            root.addHandler(self.handler)

    def shutdown(self) -> None:
        if self.handler is not None:
            logging.getLogger().removeHandler(self.handler)
        self.tracer_provider.shutdown()
        if self.logger_provider is not None:
            self.logger_provider.shutdown()


def configure_telemetry(
    *,
    service_name: str,
    version: str,
    environment: str,
    traces_endpoint: str,
    logs_endpoint: str,
    log_formatter: logging.Formatter | None = None,
    span_exporter: SpanExporter | None = None,
    log_exporter: LogRecordExporter | None = None,
    install_global: bool = True,
) -> Telemetry | None:
    """Installe traces et journaux OTLP ; None (rien d'installe) sans adresse de traces.

    span_exporter / log_exporter : remplacent l'export reseau (tests). log_formatter : le meme
    rendu JSON que la sortie standard, pour que Loki recoive des lignes identiques.
    install_global : faux dans les tests unitaires (OpenTelemetry n'accepte qu'une
    installation globale par processus, et le handler n'est alors pas ajoute aux journaux).
    """
    if not traces_endpoint and span_exporter is None:
        return None
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": version,
            "deployment.environment.name": environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    exporter = span_exporter or OTLPSpanExporter(endpoint=traces_endpoint, timeout=EXPORT_TIMEOUT_S)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(ScrubbingSpanExporter(exporter), export_timeout_millis=2000)
    )
    if install_global:
        trace.set_tracer_provider(tracer_provider)

    logger_provider: LoggerProvider | None = None
    handler: LoggingHandler | None = None
    if logs_endpoint or log_exporter is not None:
        logger_provider = LoggerProvider(resource=resource)
        logs = log_exporter or OTLPLogExporter(endpoint=logs_endpoint, timeout=EXPORT_TIMEOUT_S)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(logs, export_timeout_millis=2000)
        )
        if install_global:
            set_logger_provider(logger_provider)
        handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        # Pas de formateur sur le handler : le filtre lui remet des lignes deja mises en forme.
        handler.addFilter(export_filter(log_formatter))
        if install_global:
            logging.getLogger().addHandler(handler)
    return Telemetry(tracer_provider, logger_provider, handler)


def add_trace_ids(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Ajoute trace_id et span_id a chaque journal emis pendant une trace (structlog)."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict.setdefault("trace_id", format(context.trace_id, "032x"))
        event_dict.setdefault("span_id", format(context.span_id, "016x"))
    return event_dict


def current_trace_id() -> str | None:
    """Identifiant de la trace en cours (32 caracteres hexadecimaux), ou None sans trace."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


# --------------------------------------------------------------------- instrumentation
# Requetes de sante et metriques : pas de trace (du bruit toutes les 15 secondes).
EXCLUDED_URLS: Final = "/api/health/.*"


def instrument_app(app: Any) -> None:
    """Une trace par requete HTTP (route, methode, statut ; ni corps ni en-tetes).

    Les etapes « receive » et « send » de l'ASGI sont exclues : une reponse en flux (SSE)
    en produirait une par morceau de texte.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app, excluded_urls=EXCLUDED_URLS, exclude_spans=["receive", "send"]
    )


_SQL_TEXT_MAX: Final = 1000
_SPAN_KEY: Final = "lorakus_otel_span"


def instrument_database(engine: Any) -> None:
    """Un span par requete SQL, sur les evenements officiels de SQLAlchemy.

    Ecrit ici plutot qu'avec opentelemetry-instrumentation-sqlalchemy : ce paquet ne prend
    pas en charge SQLAlchemy 2.1 (il ne fait alors rien, sans erreur). Enregistre le texte
    SQL tel que prepare (parametres en marques de substitution), JAMAIS les valeurs.
    Idempotent : un moteur deja instrumente ne l'est pas deux fois.
    """
    sync_engine = engine.sync_engine
    if getattr(sync_engine, "_lorakus_traced", False):
        return
    tracer = trace.get_tracer("lorakus.db")

    def before(
        _conn: Any, _cursor: Any, statement: str, _params: Any, context: Any, _many: bool
    ) -> None:
        operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "SQL"
        span = tracer.start_span(
            operation,
            kind=trace.SpanKind.CLIENT,
            attributes={
                "db.system.name": "postgresql",
                "db.operation.name": operation,
                "db.query.text": statement[:_SQL_TEXT_MAX],
            },
        )
        context.__dict__[_SPAN_KEY] = span

    def after(
        _conn: Any, _cursor: Any, _statement: str, _params: Any, context: Any, _many: bool
    ) -> None:
        span = context.__dict__.pop(_SPAN_KEY, None)
        if span is not None:
            span.end()

    def failed(exception_context: Any) -> None:
        context = exception_context.execution_context
        span = context.__dict__.pop(_SPAN_KEY, None) if context is not None else None
        if span is not None:
            # Le type de l'erreur seulement : son message peut citer des valeurs.
            span.set_attribute("error.type", type(exception_context.original_exception).__name__)
            span.set_status(trace.StatusCode.ERROR)
            span.end()

    event.listen(sync_engine, "before_cursor_execute", before)
    event.listen(sync_engine, "after_cursor_execute", after)
    event.listen(sync_engine, "handle_error", failed)
    sync_engine._lorakus_traced = True
