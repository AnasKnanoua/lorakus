"""Telemetrie (PR 40) : nettoyage avant export, identifiants dans les journaux, et aucune
attente si Tempo ou Loki ne repond pas."""

import logging
import time

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lorakus.observability.telemetry import (
    ScrubbingSpanExporter,
    add_trace_ids,
    configure_telemetry,
    scrub_attributes,
)

CLOSED = "http://127.0.0.1:9"  # port ferme : rien n'y repond


def test_nothing_is_installed_without_an_endpoint() -> None:
    telemetry = configure_telemetry(
        service_name="x", version="0", environment="test", traces_endpoint="", logs_endpoint=""
    )
    assert telemetry is None


def test_query_strings_parameters_and_headers_never_leave() -> None:
    cleaned = scrub_attributes(
        {
            "http.target": "/api/v1/memory/search?q=mon+secret",
            "http.url": "https://app.lorakus.app/api/v1/memory/search?q=mon+secret#x",
            "url.full": "https://api.anthropic.com/v1/messages?beta=true",
            "url.query": "q=mon+secret",
            "db.query.parameters": "('mon secret',)",
            "http.request.header.cookie": "lorakus_session=abc",
            "http.route": "/api/v1/memory/search",
            "http.status_code": 200,
        }
    )
    assert cleaned == {
        "http.target": "/api/v1/memory/search",
        "http.url": "https://app.lorakus.app/api/v1/memory/search",
        "url.full": "https://api.anthropic.com/v1/messages",
        "http.route": "/api/v1/memory/search",
        "http.status_code": 200,
    }


def test_spans_are_scrubbed_on_their_way_out() -> None:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ScrubbingSpanExporter(memory)))
    with provider.get_tracer("t").start_as_current_span(
        "GET /api/v1/memory/search",
        attributes={"http.target": "/s?q=secret", "url.query": "q=secret"},
    ):
        pass
    (span,) = memory.get_finished_spans()
    assert dict(span.attributes or {}) == {"http.target": "/s"}
    assert span.name == "GET /api/v1/memory/search"


def test_logs_carry_the_trace_id_only_inside_a_trace() -> None:
    provider = TracerProvider()
    assert "trace_id" not in add_trace_ids(None, "info", {"event": "hors trace"})
    with provider.get_tracer("t").start_as_current_span("x") as span:
        event = add_trace_ids(None, "info", {"event": "dans la trace"})
    assert event["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert len(event["span_id"]) == 16


def test_an_unreachable_tempo_never_slows_the_application() -> None:
    """Export en arriere-plan : creer des spans reste instantane, meme sans Tempo."""
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            ScrubbingSpanExporter(OTLPSpanExporter(endpoint=f"{CLOSED}/v1/traces", timeout=1)),
            schedule_delay_millis=10,
            export_timeout_millis=1000,
        )
    )
    tracer = provider.get_tracer("t")
    started = time.monotonic()
    for index in range(200):
        with tracer.start_as_current_span(f"span-{index}"):
            pass
    assert time.monotonic() - started < 0.5
    provider.shutdown()  # rend la main malgre l'echec d'export (delai borne)


def test_an_unreachable_loki_never_slows_logging() -> None:
    provider = LoggerProvider()
    provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{CLOSED}/otlp/v1/logs", timeout=1),
            schedule_delay_millis=10,
            export_timeout_millis=1000,
        )
    )
    logger = logging.getLogger("lorakus.test.loki")
    handler = LoggingHandler(logger_provider=provider)
    logger.addHandler(handler)
    try:
        started = time.monotonic()
        for index in range(200):
            logger.warning("ligne %d", index)
        assert time.monotonic() - started < 0.5
    finally:
        logger.removeHandler(handler)
        provider.shutdown()


def test_otel_own_logs_are_not_sent_back_to_loki() -> None:
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

    exported = InMemoryLogRecordExporter()
    telemetry = configure_telemetry(
        service_name="x",
        version="0",
        environment="test",
        traces_endpoint="",
        logs_endpoint="",
        span_exporter=InMemorySpanExporter(),
        log_exporter=exported,
        install_global=False,
    )
    assert telemetry is not None and telemetry.handler is not None
    try:
        record = logging.LogRecord(
            "opentelemetry.exporter", logging.WARNING, "", 0, "echec", None, None
        )
        assert not telemetry.handler.filter(record)
        mine = logging.LogRecord("lorakus.api", logging.WARNING, "", 0, "ok", None, None)
        assert telemetry.handler.filter(mine)
    finally:
        telemetry.shutdown()
