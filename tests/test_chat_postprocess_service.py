"""Regression tests for services.chat_postprocess_service.

These cover the fire-and-forget enqueue path used when a running event loop
exists. Errors inside the detached task previously vanished — they must now
be logged, and the task must be kept alive by a strong reference so the GC
can't reap it before completion.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from services import chat_postprocess_service


@pytest.mark.asyncio
async def test_enqueue_failure_in_running_loop_is_logged(monkeypatch, caplog):
    """When the detached enqueue coroutine raises, the failure must reach the
    logger — otherwise nobody will ever notice memory persistence is broken.
    """
    async def _raise(messages, user_id, session_id):
        raise RuntimeError("redis enqueue exploded")

    monkeypatch.setattr(
        chat_postprocess_service, "_enqueue_memory_persistence", _raise
    )

    with caplog.at_level(logging.ERROR, logger="services.chat_postprocess"):
        chat_postprocess_service.schedule_memory_persistence(
            [{"role": "user", "content": "hi"}], "u-1", "s-1"
        )
        # Drain whatever the scheduler created so we observe the failure
        # deterministically rather than racing with the test runner.
        pending = list(chat_postprocess_service._pending_background_tasks)
        assert pending, "schedule_memory_persistence did not retain a task reference"
        await asyncio.gather(*pending, return_exceptions=True)

    assert any(
        "redis enqueue exploded" in rec.message
        or "memory persistence" in rec.message.lower()
        for rec in caplog.records
    ), f"expected an error log, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_pending_tasks_are_released_after_completion(monkeypatch):
    """The strong-reference set must shrink back to empty after tasks finish so
    we don't leak references for every chat turn.
    """
    async def _noop(messages, user_id, session_id):
        return None

    monkeypatch.setattr(
        chat_postprocess_service, "_enqueue_memory_persistence", _noop
    )

    chat_postprocess_service.schedule_memory_persistence(
        [{"role": "user", "content": "hi"}], "u-2", "s-2"
    )
    pending = list(chat_postprocess_service._pending_background_tasks)
    assert pending, "schedule_memory_persistence did not retain a task reference"

    await asyncio.gather(*pending, return_exceptions=True)
    # Give the done_callback a chance to fire on the event loop.
    await asyncio.sleep(0)

    assert not chat_postprocess_service._pending_background_tasks, (
        "completed tasks were not removed from the strong-reference set"
    )
