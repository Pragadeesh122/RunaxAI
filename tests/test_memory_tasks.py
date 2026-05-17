import pytest

from memory.semantic import MemoryExtractionError
from tasks import memory_tasks


class _FakeRedis:
    """Tiny in-memory stand-in for the Redis client used by memory_tasks."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)


def _install_fakes(monkeypatch, fake_redis, extractor, summarizer=None):
    monkeypatch.setattr(memory_tasks, "redis_client", fake_redis)
    monkeypatch.setattr(memory_tasks, "extract_and_persist_memories", extractor)
    monkeypatch.setattr(
        memory_tasks,
        "refresh_rolling_summary",
        summarizer or (lambda messages, previous_summary: "summary"),
    )


@pytest.mark.asyncio
async def test_cursor_skips_already_processed_messages(monkeypatch):
    """After the first run, rerunning with the same messages is a no-op."""
    calls: list[list[dict]] = []
    fake_redis = _FakeRedis()

    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: calls.append(messages) or {},
    )

    messages = [{"role": "user", "content": "I work at Acme Corp."}]

    first = await memory_tasks.persist_memories_task(
        {}, "user-1", messages, session_id="s-1"
    )
    second = await memory_tasks.persist_memories_task(
        {}, "user-1", messages, session_id="s-1"
    )

    assert first["status"] == "ok"
    assert second["status"] == "skipped_no_new_messages"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cursor_extracts_only_new_messages_on_second_run(monkeypatch):
    """Second run extracts only messages appended since the last cursor."""
    received: list[list[dict]] = []
    fake_redis = _FakeRedis()

    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: received.append(messages) or {},
    )

    first_batch = [
        {"role": "user", "content": "Hi, I'm Alice."},
        {"role": "assistant", "content": "Hello Alice."},
    ]
    second_batch = first_batch + [
        {"role": "user", "content": "I live in Berlin."},
    ]

    await memory_tasks.persist_memories_task({}, "u-1", first_batch, session_id="s-a")
    await memory_tasks.persist_memories_task({}, "u-1", second_batch, session_id="s-a")

    assert received[0] == first_batch
    assert received[1] == [{"role": "user", "content": "I live in Berlin."}]


@pytest.mark.asyncio
async def test_cursor_recovers_when_summarization_collapses_messages(monkeypatch):
    """If the cursor message was collapsed into a summary, extract the full
    current conversation rather than silently skipping.
    """
    received: list[list[dict]] = []
    fake_redis = _FakeRedis()

    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: received.append(messages) or {},
    )

    pre = [
        {"role": "user", "content": f"turn {i}"} for i in range(3)
    ]
    await memory_tasks.persist_memories_task({}, "u-2", pre, session_id="s-b")

    # Simulate summarization: the conversation has been collapsed into a
    # summary + a couple of fresh turns. None of the old cursor messages
    # appear in the new list.
    after_summary = [
        {"role": "system", "content": "Summary: user said hi three times."},
        {"role": "user", "content": "Now tell me about Python."},
    ]
    await memory_tasks.persist_memories_task({}, "u-2", after_summary, session_id="s-b")

    assert received[0] == pre
    # Fallback: extracted the full post-summary list (both messages),
    # not an empty slice.
    assert received[1] == after_summary


@pytest.mark.asyncio
async def test_invalidate_cursor_forces_full_extraction(monkeypatch):
    """After invalidate_session_memory_cursor, the next run treats the
    conversation as fresh.
    """
    received: list[list[dict]] = []
    fake_redis = _FakeRedis()

    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: received.append(messages) or {},
    )

    messages = [{"role": "user", "content": "I'm building AgenticRag."}]

    await memory_tasks.persist_memories_task({}, "u-3", messages, session_id="s-c")
    memory_tasks.invalidate_session_memory_cursor("s-c")
    await memory_tasks.persist_memories_task({}, "u-3", messages, session_id="s-c")

    assert len(received) == 2
    assert received[0] == messages
    assert received[1] == messages


@pytest.mark.asyncio
async def test_lock_prevents_concurrent_execution(monkeypatch):
    """While a task is holding the lock, a second invocation returns in_progress."""
    fake_redis = _FakeRedis()

    def _hang(messages, user_id, session_id, rolling_summary):
        # First run: lock is held; second concurrent invocation can't acquire.
        assert not fake_redis.set(
            memory_tasks._lock_key("s-d"), "1", ex=60, nx=True
        )
        return {}

    _install_fakes(monkeypatch, fake_redis, _hang)

    result = await memory_tasks.persist_memories_task(
        {}, "u-4", [{"role": "user", "content": "hi"}], session_id="s-d"
    )
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_cursor_does_not_advance_on_extraction_failure(monkeypatch):
    """Hard parse failures inside extraction must NOT advance the cursor —
    otherwise the same conversation can never be retried and its facts are
    lost forever. The task should surface an explicit failure status and the
    lock must be released so subsequent attempts can run.
    """
    fake_redis = _FakeRedis()

    def _raise(messages, user_id, session_id, rolling_summary):
        raise MemoryExtractionError("simulated parse failure")

    _install_fakes(monkeypatch, fake_redis, _raise)

    messages = [{"role": "user", "content": "I built it with FastAPI."}]
    result = await memory_tasks.persist_memories_task(
        {}, "u-fail", messages, session_id="s-fail"
    )

    assert result["status"] == "extraction_failed"
    assert fake_redis.get(memory_tasks._cursor_key("s-fail")) is None, (
        "cursor was advanced despite an extraction failure — the failed "
        "messages will never be retried"
    )
    assert fake_redis.get(memory_tasks._lock_key("s-fail")) is None, (
        "lock was not released after failure"
    )


@pytest.mark.asyncio
async def test_failed_extraction_is_retried_on_next_invocation(monkeypatch):
    """After a failure, the next invocation must reprocess the same messages
    end-to-end rather than skipping them as already-processed.
    """
    fake_redis = _FakeRedis()
    received: list[list[dict]] = []

    def _raise(messages, user_id, session_id, rolling_summary):
        raise MemoryExtractionError("simulated parse failure")

    _install_fakes(monkeypatch, fake_redis, _raise)

    messages = [{"role": "user", "content": "I prefer Postgres over MySQL."}]
    await memory_tasks.persist_memories_task(
        {}, "u-retry", messages, session_id="s-retry"
    )

    # Now swap in a successful extractor and call again.
    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: received.append(messages) or {},
    )
    result = await memory_tasks.persist_memories_task(
        {}, "u-retry", messages, session_id="s-retry"
    )

    assert result["status"] == "ok"
    assert received == [messages], (
        "second attempt did not reprocess the messages after a failed first run"
    )


@pytest.mark.asyncio
async def test_persist_task_refreshes_summary_every_tenth_user_turn(monkeypatch):
    fake_redis = _FakeRedis()
    summary_calls = []

    _install_fakes(
        monkeypatch,
        fake_redis,
        lambda messages, user_id, session_id, rolling_summary: {},
        summarizer=lambda messages, previous_summary: summary_calls.append(
            (messages, previous_summary)
        ) or "summary-v1",
    )

    messages = [{"role": "user", "content": f"turn {i}"} for i in range(10)]

    result = await memory_tasks.persist_memories_task(
        {}, "u-5", messages, session_id="s-e"
    )

    assert result["status"] == "ok"
    assert len(summary_calls) == 1
    assert summary_calls[0][0] == messages
    assert fake_redis.get(memory_tasks._summary_key("s-e")) == "summary-v1"


@pytest.mark.asyncio
async def test_refresh_rolling_summary_task_persists_summary(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(memory_tasks, "redis_client", fake_redis)
    fake_redis.set(memory_tasks._summary_key("s-f"), "previous summary")

    calls = []
    monkeypatch.setattr(
        memory_tasks,
        "refresh_rolling_summary",
        lambda messages, previous_summary: calls.append(
            (messages, previous_summary)
        ) or "updated summary",
    )

    messages = [{"role": "user", "content": "I switched to FastAPI."}]
    result = await memory_tasks.refresh_rolling_summary_task({}, messages, "s-f")

    assert result["status"] == "ok"
    assert calls == [(messages, "previous summary")]
    assert fake_redis.get(memory_tasks._summary_key("s-f")) == "updated summary"
