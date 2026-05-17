import asyncio
import logging
import os
from typing import Optional

from arq import create_pool
from arq.connections import RedisSettings

logger = logging.getLogger("services.chat_postprocess")

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", "6379"))


# Strong references to in-flight detached enqueue tasks. Without this set the
# event loop only keeps weak references and tasks can be garbage collected
# before they finish. The done-callback removes the task on completion so the
# set doesn't grow unboundedly.
_pending_background_tasks: set[asyncio.Task] = set()


def _handle_background_task_done(task: asyncio.Task) -> None:
    _pending_background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "background memory persistence task failed: %s", exc, exc_info=exc
        )


def _spawn_background(coro) -> asyncio.Task:
    """Schedule a coroutine on the running loop with strong-ref tracking and
    exception logging.
    """
    task = asyncio.get_running_loop().create_task(coro)
    _pending_background_tasks.add(task)
    task.add_done_callback(_handle_background_task_done)
    return task


def _normalize_memory_messages(messages: list[dict]) -> list[dict]:
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in messages
        if isinstance(msg, dict)
        and msg.get("role") in ("user", "assistant")
        and msg.get("content")
    ]


async def _enqueue_memory_persistence(
    messages: list[dict],
    user_id: str,
    session_id: Optional[str],
) -> None:
    pool = await create_pool(RedisSettings(host=redis_host, port=redis_port))
    await pool.enqueue_job(
        "persist_memories_task", user_id, messages, session_id
    )


async def _enqueue_memory_summary_refresh(
    messages: list[dict],
    session_id: str,
) -> None:
    pool = await create_pool(RedisSettings(host=redis_host, port=redis_port))
    await pool.enqueue_job(
        "refresh_rolling_summary_task", messages, session_id
    )


def schedule_memory_persistence(
    messages: list[dict],
    user_id: str,
    session_id: Optional[str] = None,
) -> None:
    normalized_messages = _normalize_memory_messages(messages)
    if not user_id or not normalized_messages:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(
                _enqueue_memory_persistence(normalized_messages, user_id, session_id)
            )
        except Exception as exc:
            logger.error(f"failed to enqueue memory persistence: {exc}")
        return

    _spawn_background(
        _enqueue_memory_persistence(normalized_messages, user_id, session_id)
    )


def schedule_memory_summary_refresh(
    messages: list[dict],
    session_id: Optional[str],
) -> None:
    normalized_messages = _normalize_memory_messages(messages)
    if not session_id or not normalized_messages:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(
                _enqueue_memory_summary_refresh(normalized_messages, session_id)
            )
        except Exception as exc:
            logger.error(f"failed to enqueue rolling summary refresh: {exc}")
        return

    _spawn_background(
        _enqueue_memory_summary_refresh(normalized_messages, session_id)
    )
