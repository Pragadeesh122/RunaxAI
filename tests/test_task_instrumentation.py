"""Tests for the ARQ task instrumentation wrapper and trace propagation."""

import unittest
from unittest.mock import patch

from observability.propagation import extract_trace_context, inject_trace_context
from observability.task_instrumentation import instrumented_task


class _Boom(Exception):
    pass


class TaskInstrumentationTests(unittest.IsolatedAsyncioTestCase):
    @patch("observability.task_instrumentation.observe_worker_task")
    async def test_success_records_metric_and_passes_args(self, observe_mock):
        seen = {}

        @instrumented_task
        async def my_task(ctx, a, b=None):
            seen["args"] = (ctx, a, b)
            return "done"

        result = await my_task({"redis": None}, "x", b="y")

        self.assertEqual(result, "done")
        self.assertEqual(seen["args"], ({"redis": None}, "x", "y"))
        observe_mock.assert_called_once()
        kwargs = observe_mock.call_args.kwargs
        self.assertEqual(kwargs["task_name"], "my_task")
        self.assertEqual(kwargs["status"], "success")
        self.assertGreaterEqual(kwargs["duration_seconds"], 0)

    @patch("observability.task_instrumentation.observe_worker_task")
    async def test_trace_kwarg_is_consumed_not_forwarded(self, observe_mock):
        seen = {}

        @instrumented_task
        async def my_task(ctx, a):
            seen["a"] = a
            return a

        # A task body without **kwargs must not receive _trace.
        await my_task({}, "value", _trace={"traceparent": "00-abc-def-01"})
        self.assertEqual(seen["a"], "value")
        observe_mock.assert_called_once()

    @patch("observability.task_instrumentation.observe_worker_task")
    async def test_error_records_error_status_and_reraises(self, observe_mock):
        @instrumented_task
        async def failing_task(ctx):
            raise _Boom("nope")

        with self.assertRaises(_Boom):
            await failing_task({})

        self.assertEqual(observe_mock.call_args.kwargs["status"], "error")

    @patch("observability.task_instrumentation.observe_worker_task")
    async def test_preserves_name_for_arq_registration(self, _observe_mock):
        @instrumented_task
        async def process_document_task(ctx):
            return None

        # ARQ registers functions by __name__; the wrapper must not rename it.
        self.assertEqual(process_document_task.__name__, "process_document_task")


class TracePropagationTests(unittest.TestCase):
    def test_inject_without_active_span_returns_dict(self):
        carrier = inject_trace_context()
        self.assertIsInstance(carrier, dict)

    def test_extract_of_empty_carrier_is_none(self):
        self.assertIsNone(extract_trace_context({}))
        self.assertIsNone(extract_trace_context(None))

    def test_round_trip_with_recording_tracer(self):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
        except ImportError:  # pragma: no cover
            self.skipTest("opentelemetry sdk not installed")

        # A locally-created provider (not the global no-op) gives recording
        # spans whose context should survive the inject/extract round trip.
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("parent") as span:
            carrier = inject_trace_context()
            self.assertIn("traceparent", carrier)
            ctx = extract_trace_context(carrier)
            self.assertIsNotNone(ctx)
            restored = trace.get_current_span(ctx).get_span_context()
            self.assertEqual(
                restored.trace_id, span.get_span_context().trace_id
            )
