"""Structured logging configuration."""

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        # Include OpenTelemetry trace ID if available
        trace_id = getattr(record, "otelTraceID", "0" * 32)
        if trace_id != "0" * 32:
            entry["trace_id"] = trace_id
        span_id = getattr(record, "otelSpanID", "0" * 16)
        if span_id != "0" * 16:
            entry["span_id"] = span_id
        return json.dumps(entry, default=str)


# Loggers from third-party libraries that flood the output with redundant
# INFO lines (one for every chat completion, every embedding, every retry).
# We pin them at WARNING so real signals are visible. Override per-logger via
# LOG_LEVEL_<NAME>=DEBUG if you need to debug a specific library.
_NOISY_LOGGERS = (
    "LiteLLM",
    "litellm",
    "litellm.utils",
    "litellm.cost_calculator",
    "httpx",
    "httpcore",
    "openai._base_client",
)

# Endpoints hit by automated scrapers (Prometheus, k8s health probes). Each
# scrape produces one uvicorn.access INFO line, which floods the log every
# few seconds. Override via SILENT_ACCESS_PATHS="/metrics,/health,/foo".
_DEFAULT_SILENT_ACCESS_PATHS = ("/metrics", "/health", "/ready")


class _DropAccessPaths(logging.Filter):
    """Drop uvicorn.access records for high-frequency probe endpoints.

    uvicorn formats access lines as:
        '%s - "%s %s HTTP/%s" %d'  with args = (client, method, path, ver, status)
    so we filter on `record.args[2]` (the path).
    """

    def __init__(self, silenced_paths: tuple[str, ...]) -> None:
        super().__init__()
        self._paths = silenced_paths

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.split("?", 1)[0] in self._paths:
                return False
        return True


def setup_logging() -> None:
    """Configure root logger based on LOG_FORMAT env var.

    LOG_FORMAT=json  -> JSON lines (for production / log aggregation)
    Otherwise        -> plain text (for local development)
    """
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(name)s | %(message)s")
        )

    root.addHandler(handler)

    # Quiet third-party loggers. Without this we get 4 lines per LLM call:
    # LiteLLM attaches its own StreamHandler AND propagates to root, so each
    # message gets emitted twice in two different formats.
    for noisy in _NOISY_LOGGERS:
        override = os.getenv(f"LOG_LEVEL_{noisy.replace('.', '_').upper()}")
        target = (override or "WARNING").upper()
        lg = logging.getLogger(noisy)
        lg.setLevel(target)
        # Strip the library's own handlers and let our root formatter handle
        # whatever survives the level filter.
        lg.handlers.clear()
        lg.propagate = True

    # Drop access logs for /metrics, /health, etc. — they're scraped on a
    # short interval and otherwise drown out real request logs.
    silent_paths_env = os.getenv("SILENT_ACCESS_PATHS")
    silent_paths = (
        tuple(p.strip() for p in silent_paths_env.split(",") if p.strip())
        if silent_paths_env
        else _DEFAULT_SILENT_ACCESS_PATHS
    )
    if silent_paths:
        access_filter = _DropAccessPaths(silent_paths)
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.addFilter(access_filter)
        # Also attach to the catch-all uvicorn logger in case `--access-log`
        # output gets routed through it under some configurations.
        logging.getLogger("uvicorn").addFilter(access_filter)
