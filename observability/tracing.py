"""OpenTelemetry tracing setup — OTLP export + auto-instrumentation."""

from __future__ import annotations

import os
import logging

logger = logging.getLogger("observability.tracing")

_INITIALIZED = False


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def setup_tracing(app=None, *, service_name: str | None = None) -> None:
    """Wire TracerProvider, OTLP exporter, and auto-instrumentors.

    Idempotent. Gated behind ``OTEL_ENABLED`` env var (default ``false``).

    ``app`` is optional so non-FastAPI processes (the ARQ worker) can share
    the same setup — FastAPI instrumentation is skipped when app is None.
    ``service_name`` overrides OTEL_SERVICE_NAME so each process reports as
    its own service in Tempo (api = "agenticrag", worker = "agenticrag-worker").
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    if not _env_bool("OTEL_ENABLED"):
        logger.info("OpenTelemetry tracing disabled (OTEL_ENABLED is not set)")
        _INITIALIZED = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
        )

        resource = Resource.create({
            "service.name": service_name
            or os.getenv("OTEL_SERVICE_NAME", "agenticrag"),
            "service.version": "0.1.0",
        })

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrumentors — each is optional so a missing package won't block startup.
        if app is not None:
            _instrument_fastapi(app)
        _instrument_redis()
        _instrument_sqlalchemy()
        _instrument_httpx()
        _instrument_logging()

        logger.info("OpenTelemetry tracing enabled (endpoint=%s)", endpoint)
    except Exception:
        logger.exception("Failed to initialize OpenTelemetry tracing")

    _INITIALIZED = True


def _instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        logger.debug("FastAPI auto-instrumentation skipped", exc_info=True)


def _instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
    except Exception:
        logger.debug("Redis auto-instrumentation skipped", exc_info=True)


def _instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from database.core import engine, sync_engine
        # Both engines: sync_engine serves memory/semantic sync sessions; the
        # async engine (via its underlying sync core) serves everything else.
        # Instrumenting only sync_engine left every async query without spans.
        SQLAlchemyInstrumentor().instrument(engine=sync_engine)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except Exception:
        logger.debug("SQLAlchemy auto-instrumentation skipped", exc_info=True)


def _instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception:
        logger.debug("HTTPX auto-instrumentation skipped", exc_info=True)


def _instrument_logging() -> None:
    """Stamp otelTraceID/otelSpanID onto every LogRecord.

    JSONFormatter (observability/logging_config.py) already reads these
    attributes to emit trace_id/span_id — without this instrumentor nothing
    sets them, so Loki logs could never be joined to Tempo traces.
    set_logging_format=False: we keep our own formatter.
    """
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception:
        logger.debug("logging auto-instrumentation skipped", exc_info=True)


def get_tracer(name: str = "agenticrag"):
    """Return a tracer, falling back to a no-op if OTel is not initialised."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        return None
