"""Instrumentation wrapper for ARQ task functions.

Wraps a task so that every execution:
  - continues the caller's trace via the optional ``_trace`` carrier kwarg
    (injected at enqueue time by observability.propagation.inject_trace_context)
  - runs inside an ``arq.task <name>`` span
  - records agenticrag_worker_tasks_total / _duration_seconds Prometheus metrics

``_trace`` is consumed here and never reaches the task body, so task
signatures stay unchanged. Exceptions propagate unchanged (ARQ retry
semantics are untouched); status is "error" only when one escapes.
"""

from __future__ import annotations

import functools
import time
import logging

from observability.metrics import observe_worker_task
from observability.propagation import extract_trace_context

logger = logging.getLogger("observability.tasks")


def instrumented_task(fn):
    task_name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(ctx, *args, _trace=None, **kwargs):
        parent_ctx = extract_trace_context(_trace)
        started = time.perf_counter()
        status = "success"

        span_cm = _task_span(task_name, parent_ctx)
        try:
            with span_cm:
                return await fn(ctx, *args, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            observe_worker_task(
                task_name=task_name,
                status=status,
                duration_seconds=time.perf_counter() - started,
            )

    return wrapper


def _task_span(task_name: str, parent_ctx):
    """Start an arq.task span under parent_ctx; no-op when OTel is absent."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("agenticrag.worker")
        return tracer.start_as_current_span(
            f"arq.task {task_name}",
            context=parent_ctx,
            attributes={"arq.task_name": task_name},
        )
    except Exception:
        import contextlib

        return contextlib.nullcontext()
