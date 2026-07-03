"""W3C trace-context propagation across the ARQ queue boundary.

The API process enqueues jobs into Redis; the worker executes them in a
different process, so OpenTelemetry's implicit context does not cross over.
These helpers serialize the current trace context into a plain dict that
rides along as a job kwarg, and rebuild it on the worker side so an upload
request and its ingestion task appear as one trace.

Every function degrades to a no-op when OpenTelemetry is unavailable or
tracing is disabled — callers never need to guard.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("observability.propagation")


def inject_trace_context() -> dict[str, str]:
    """Capture the active trace context as a {traceparent, ...} carrier dict.

    Returns an empty dict when there is no active span or OTel is missing.
    """
    try:
        from opentelemetry.propagate import inject

        carrier: dict[str, str] = {}
        inject(carrier)
        return carrier
    except Exception:
        return {}


def extract_trace_context(carrier: Optional[dict[str, str]]) -> Any:
    """Rebuild an OTel Context from a carrier dict, or None if not possible."""
    if not carrier:
        return None
    try:
        from opentelemetry.propagate import extract

        return extract(carrier)
    except Exception:
        return None
