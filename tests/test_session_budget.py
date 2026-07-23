"""Tests for the per-session spend guardrail (api/session_budget.py) and the
retrieval-latency / guardrail metrics added for LLM cost & latency observability."""

import unittest
from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY

import api.session_budget as sb
from observability.metrics import (
    SESSION_BUDGET_BLOCKED_TOTAL,
    observe_retrieval_latency,
    observe_session_budget_blocked,
)


def _count(metric: str, **labels) -> float:
    return REGISTRY.get_sample_value(metric, labels) or 0.0


class SessionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.redis = MagicMock()
        self._patcher = patch.object(sb, "redis_client", self.redis)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_under_ceiling_is_allowed(self):
        self.redis.get.return_value = "500"
        status = sb.check_session_budget("sess-1")
        self.assertTrue(status.allowed)
        self.assertEqual(status.used_tokens, 500)
        self.assertEqual(status.ceiling, 1000)
        self.assertEqual(status.remaining, 500)

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_at_or_over_ceiling_is_blocked(self):
        self.redis.get.return_value = "1000"
        status = sb.check_session_budget("sess-1")
        self.assertFalse(status.allowed)
        self.assertEqual(status.remaining, 0)

    @patch.object(sb, "MAX_SESSION_TOKENS", 0)
    def test_zero_ceiling_disables_enforcement(self):
        status = sb.check_session_budget("sess-1")
        self.assertTrue(status.allowed)
        self.redis.get.assert_not_called()

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_record_increments_and_refreshes_ttl(self):
        self.redis.incrby.return_value = 700
        sb.record_session_tokens("sess-1", 400, 300)
        self.redis.incrby.assert_called_once_with("session:sess-1:tokens", 700)
        self.redis.expire.assert_called_once()

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_record_ignores_zero_usage(self):
        sb.record_session_tokens("sess-1", 0, 0)
        self.redis.incrby.assert_not_called()

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_check_fails_open_on_redis_error(self):
        self.redis.get.side_effect = RuntimeError("redis down")
        status = sb.check_session_budget("sess-1")
        self.assertTrue(status.allowed)

    @patch.object(sb, "MAX_SESSION_TOKENS", 1000)
    def test_empty_session_id_is_allowed(self):
        status = sb.check_session_budget("")
        self.assertTrue(status.allowed)
        self.redis.get.assert_not_called()


class MetricsTests(unittest.TestCase):
    def test_retrieval_latency_records_by_cache_status(self):
        metric = "agenticrag_retrieval_duration_seconds_count"
        before = _count(metric, cache_status="hit")
        observe_retrieval_latency(cache_hit=True, duration_seconds=0.012)
        after = _count(metric, cache_status="hit")
        self.assertEqual(after, before + 1)

    def test_negative_latency_is_ignored(self):
        metric = "agenticrag_retrieval_duration_seconds_count"
        before = _count(metric, cache_status="miss")
        observe_retrieval_latency(cache_hit=False, duration_seconds=-1.0)
        after = _count(metric, cache_status="miss")
        self.assertEqual(after, before)

    def test_session_budget_blocked_counter_increments(self):
        before = SESSION_BUDGET_BLOCKED_TOTAL.labels(
            chat_type="general", limit="session_tokens"
        )._value.get()
        observe_session_budget_blocked(chat_type="general", limit="session_tokens")
        after = SESSION_BUDGET_BLOCKED_TOTAL.labels(
            chat_type="general", limit="session_tokens"
        )._value.get()
        self.assertEqual(after, before + 1)


if __name__ == "__main__":
    unittest.main()
